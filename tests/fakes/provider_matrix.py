"""Independent JSON-backed HTTP services behind the actual production adapters."""
import json
from types import SimpleNamespace

import httpx

from mailhelp.external.caldav import AppleReminders, CalDavCalendar, CalDavTasks
from mailhelp.external.http_writer import HttpWriter
from mailhelp.external.microsoft import MicrosoftTodo, OutlookCalendar
from mailhelp.storage import atomic_replace

PROVIDERS=('google_calendar','todoist','outlook_calendar','microsoft_todo','caldav_calendar','caldav_tasks','apple_reminders')


class ProviderMemory:
    def __init__(self,path,provider,uncertain=False):
        self.path,self.provider,self.uncertain=path,provider,uncertain
        self.before=lambda request:None
        self.after_write=lambda:None

    def state(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {'calls':[],'items':[],'dav':{}}

    def handle(self,request):
        self.before(request)
        state=self.state()
        state['calls'].append({'method':request.method,'url':str(request.url),'headers':dict(request.headers)})
        if request.method=='DELETE':
            state['items']=[]
            atomic_replace(self.path,json.dumps(state))
            self.after_write()
            return httpx.Response(204)
        if request.method in {'POST','PUT','PATCH'}:
            if self.provider.startswith(('caldav','apple')):
                state['dav'][str(request.url)]=request.content.decode()
                response=httpx.Response(201)
            else:
                body=json.loads(request.content)
                body['id']='created-1'
                if self.provider=='todoist':
                    # Like Todoist: the answer carries the due object, not the request fields.
                    due=body.get('due_date') or body.get('due_datetime')
                    body['due']=None if due is None else {'date':due}
                state['items']=[body]
                response=httpx.Response(200,json=body)
            atomic_replace(self.path,json.dumps(state))
            self.after_write()
            if self.uncertain:
                raise httpx.ReadTimeout('synthetic response lost',request=request)
            return response
        atomic_replace(self.path,json.dumps(state))
        if request.method=='REPORT':
            return httpx.Response(207,content=b'<d:multistatus xmlns:d="DAV:"/>')
        if self.provider.startswith(('caldav','apple')):
            value=state['dav'].get(str(request.url))
            return httpx.Response(200,content=value.encode(),headers={'ETag':'"synthetic"'}) if value else httpx.Response(404)
        read=self.single_read(request.url.path,state)
        if read is not None:
            return read
        if self.provider=='todoist':
            return httpx.Response(200,json={'results':state['items'],'next_cursor':None})
        if self.provider=='google_calendar':
            key=request.url.params.get('privateExtendedProperty','').removeprefix('mailhelp_key=')
            items=[item for item in state['items'] if not key or
                   item.get('extendedProperties',{}).get('private',{}).get('mailhelp_key')==key]
            return httpx.Response(200,json={'items':items})
        import re
        found=re.search(r"ep/value eq '([^']+)'",request.url.params.get('$filter',''))
        items=[item for item in state['items'] if not found or any(
            prop.get('value')==found.group(1) for prop in item.get('singleValueExtendedProperties',[]))]
        return httpx.Response(200,json={'value':items})

    def single_read(self,path,state):
        """Reads of one resource: account bindings (5.2), projects and entries by id (4.6, 5.2)."""
        if path in {'/api/v1/user','/v1.0/me'}:
            return httpx.Response(200,json={'id':'synthetic-user'})
        if path=='/api/v1/tasks/completed/by_completion_date':
            return httpx.Response(200,json={'items':[],'next_cursor':None})
        if self.provider=='todoist' and path.startswith('/api/v1/projects/'):
            return httpx.Response(200,json={'id':path.rsplit('/',1)[1]})
        if self.provider=='google_calendar' and path.count('/')==4:
            # The calendar resource names the account behind an alias such as primary.
            return httpx.Response(200,json={'id':'synthetic-owner@example.test'})
        by_id=('/events/' in path or (self.provider=='todoist' and path.startswith('/api/v1/tasks/'))
               or (self.provider=='microsoft_todo' and '/tasks/' in path))
        if not by_id:
            return None
        wanted=path.rsplit('/',1)[1]
        found_item=next((item for item in state['items'] if item.get('id')==wanted),None)
        return httpx.Response(200,json=found_item) if found_item else httpx.Response(404)

    def writer(self):
        transport=httpx.MockTransport(self.handle)
        if self.provider in {'google_calendar','todoist'}:
            return HttpWriter(self.provider,'synthetic-token','synthetic-target',transport=transport,calendar_timezone='UTC')
        if self.provider in {'outlook_calendar','microsoft_todo'}:
            cls=OutlookCalendar if self.provider=='outlook_calendar' else MicrosoftTodo
            return cls(SimpleNamespace(access_token=lambda:'synthetic-token',invalidate=lambda:None),'synthetic-target',transport=transport)
        cls={'caldav_calendar':CalDavCalendar,'caldav_tasks':CalDavTasks,'apple_reminders':AppleReminders}[self.provider]
        return cls('https://dav.example.test/synthetic/','synthetic-user','synthetic-password',transport=transport)

    def writes(self):
        return [call for call in self.state()['calls'] if call['method'] in {'POST','PUT','PATCH','DELETE'}]
