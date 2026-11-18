"""7.8: synthetic English original messages; analysed by the ordinary Mailhelp pipeline."""
from .mails import DemoMail

RECIPIENT = "Alex Miller <alex@miller-family.example>"
PERSONA = ("I am Alex Miller, Mia's parent. Mia attends class 4B at Maple Park Elementary School, "
           "plays at Oakville Sports Club and studies violin at Oakville Music School. "
           "I volunteer with the school's PTA and live at 5 Maple Lane. School, music and club "
           "messages for Mia concern me. General advertisements and optional public events do not.")
TOPICS = [
    {"id": "school", "name": "School and class 4B", "enabled": True,
     "description": "Messages from Maple Park Elementary School and Mia's class teacher or school office.",
     "examples": ["Parent meeting", "Consent form", "School trip", "School information"], "exclusions": []},
    {"id": "sports", "name": "Oakville Sports Club", "enabled": True,
     "description": "Messages from Oakville Sports Club and its youth section.",
     "examples": ["Training", "Workshop", "Bring materials"], "exclusions": ["Third-party advertising"]},
    {"id": "music", "name": "Music school", "enabled": True,
     "description": "Oakville Music School messages about Mia's violin lessons.",
     "examples": ["Recital", "Lesson"], "exclusions": []},
    {"id": "pta", "name": "PTA and school events", "enabled": True,
     "description": "Messages from the Maple Park PTA about volunteering and school events.",
     "examples": ["Winter fair", "Cake donation"], "exclusions": []},
]

RELEVANT = (
    DemoMail("01-parent-meeting", "Jane Lewis <lewis@maple-park-school.example>",
             "Class 4B parent meeting", "2026-11-09 16:12",
             "Dear parents of class 4B,\nOur parent meeting is on 2026-11-26, 19:30–21:00, "
             "in Room 12, Maple Park Elementary School. We will discuss the planetarium trip, "
             "reading mentors and the school calendar. All times are Europe/Berlin.\nJane Lewis"),
    DemoMail("02-planetarium-trip", "Jane Lewis <lewis@maple-park-school.example>",
             "Planetarium trip: your chaperone assignment and Mia's consent form", "2026-11-10 07:48",
             "Dear Alex,\nThank you for agreeing to accompany class 4B to the planetarium. You are "
             "confirmed as a chaperone on 2026-12-04, 08:30–13:00, meeting in the school courtyard. "
             "Please also hand in Mia's signed consent form to the school office by 2026-11-20. "
             "All times are Europe/Berlin.\nJane Lewis"),
    DemoMail("03-craft-workshop", "Tom Walker <youth@oakville-sports.example>",
             "Our craft workshop: please buy the materials", "2026-11-10 19:05",
             "Hi Alex,\nThanks for co-hosting the youth craft workshop with me on 2026-11-21, "
             "10:00–12:30, at the Oakville Sports Club clubhouse. Please buy two packs of craft glue "
             "and a pad of coloured A4 card by 2026-11-20 and bring them to the workshop. "
             "All times are Europe/Berlin.\nTom"),
    DemoMail("04-winter-fair", "Maple Park PTA <committee@maple-park-pta.example>",
             "Winter fair: thank you for your cake donation", "2026-11-11 12:30",
             "Dear Alex,\nWe look forward to seeing you at our winter fair on 2026-12-05, 14:00–17:00, "
             "in the Maple Park Elementary School hall. Thank you for donating a chocolate cake. "
             "Please deliver it to the school hall by 2026-12-05 at 13:30. "
             "All times are Europe/Berlin.\nYour PTA committee"),
    DemoMail("05-reading-mentors", "Jane Lewis <lewis@maple-park-school.example>",
             "Reading mentors: your introductory meeting", "2026-11-12 14:20",
             "Dear Alex,\nWelcome as a reading mentor for class 4B. Your introductory meeting "
             "is on 2026-12-01, 18:00–19:00, in the school library. "
             "All times are Europe/Berlin.\nJane Lewis"),
    DemoMail("06-admission-fee", "School office <office@maple-park-school.example>",
             "Planetarium admission: please transfer EUR 12", "2026-11-13 08:15",
             "Dear parents of class 4B,\nPlease transfer EUR 12 for your child's planetarium admission "
             "to the class account by 2026-11-25. Use Planetarium and your child's name as the reference. "
             "This is the payment request; it has not yet been paid.\nSchool office"),
    DemoMail("07-violin-recital", "Oakville Music School <office@oakville-music.example>",
             "Mia's violin recital", "2026-11-13 17:40",
             "Dear parents,\nMia will perform her first solo at the violin class recital on "
             "2026-12-09, 16:00–17:30, in the Chamber Music Hall at Oakville Music School. "
             "We warmly invite you to attend. All times are Europe/Berlin.\nYour music school"),
    DemoMail("08-team-jerseys", "Tom Walker <youth@oakville-sports.example>",
             "The new youth team jerseys have arrived", "2026-11-14 10:02",
             "Hello everyone,\nThe new youth team jerseys are here. We will give them to the children "
             "during their next regular training session. No payment or action is needed from parents.\nTom"),
    DemoMail("09-cafeteria-menu", "School office <office@maple-park-school.example>",
             "Your school's cafeteria menu", "2026-11-14 11:15",
             "Dear parents,\nNext week's Maple Park school menu offers vegetable pasta, rice bowls "
             "and soup. Mia's existing meal plan remains unchanged. This is for your information; "
             "no order, reply or payment is required.\nSchool office"),
    DemoMail("10-library-return", "Maple Park school library <library@maple-park-school.example>",
             "Please return Mia's library book", "2026-11-16 08:10",
             "Dear Alex,\nPlease return Mia's copy of The Secret Garden to the Maple Park school "
             "library by 2026-11-30. The book is still checked out to Mia.\nYour school librarian"),
)

_NEGATIVES = (
    ("black-week", "Black Week: up to 60% off", (
        'Our public Black Week sale has started. Discover gadgets and '
        'discounted subscriptions.'
    )),
    ("newsletter", "This week's technology news", (
        'Read our weekly roundup of general technology news and product '
        'releases.'
    )),
    ("shipping", "Your parcel is on its way", (
        'Your already-paid order has shipped. No signature or collection '
        'is required.'
    )),
    ("receipt", "Receipt for your completed purchase", (
        'Payment received. Your purchase is complete; nothing remains to '
        'be paid.'
    )),
    ("public-concert", "Optional city concert this weekend", (
        'A public concert is open to everyone. This is advertising, not a '
        'booking or commitment.'
    )),
    ("password", "Your password was changed", (
        'Automatic notification: your requested password change '
        'succeeded. No action is needed.'
    )),
    ("social", "New activity on your social feed", (
        'There are new public posts to discover. This is an automatic '
        'platform notification.'
    )),
    ("travel", "Sunny holidays at special prices", "Browse our general travel offers. You have no booking with us."),
    ("fashion", (
        'Discover the new autumn collection'
    ), (
        'Our latest clothing collection is available in the online shop.'
    )),
    ("streaming", "New films this month", (
        'Here are the new releases in our streaming catalogue. Your plan '
        'is unchanged.'
    )),
    ("survey", "Optional customer satisfaction survey", (
        'Would you like to take an optional anonymous survey? There is no '
        'obligation.'
    )),
    ("property", "New properties in your area", (
        'Our public property newsletter presents homes for sale. This is '
        'not a viewing appointment.'
    )),
    ("delivery-complete", "Delivery completed", (
        'Your parcel was delivered successfully. There is nothing to '
        'collect or confirm.'
    )),
    ("software", "Premium upgrade sale", (
        'Buy more cloud storage and premium templates. This is a general '
        'promotional offer.'
    )),
    ("hotel", "Weekend spa offers", "Browse our public hotel offers. This email does not confirm a reservation."),
    ("insurance", "Compare home insurance", "Use our optional online comparison tool to find insurance offers."),
    ("sports-sale", "Sportswear outlet promotion", (
        "A retailer's public sale of sportswear. Not a message from "
        'Oakville Sports Club.'
    )),
    ("digest", "Your automatic account digest", (
        'Your account has no outstanding balance, requests or upcoming '
        'bookings.'
    )),
    ("food-sale", "Restaurant discount newsletter", (
        'Our public promotion offers discounts on optional meals. No '
        'booking exists.'
    )),
    ("job-alert", "Automatic job recommendations", (
        'Browse these optional vacancies generated from public listings. '
        'No interview is arranged.'
    )),
)
IRRELEVANT = tuple(DemoMail(f"{index:02d}-{name}", f"Public updates <news@{name}.example>", subject,
                            f"2026-11-{12 + (index - 11) // 5:02d} 09:{index:02d}", body)
                   for index, (name, subject, body) in enumerate(_NEGATIVES, 11))
MAILS = RELEVANT + IRRELEVANT
