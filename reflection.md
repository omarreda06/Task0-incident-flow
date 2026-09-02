# Reflection

## What was the hardest part?

Honestly, the AI part wasn't the hard part. The hard part was ServiceNow just not letting me log in.

I set everything up the way the guide said — username and password, basic auth. But I kept getting "401 Unauthorized" no matter what I tried. I checked my password, changed it, checked for typos, nothing worked. Turns out ServiceNow recently started blocking that kind of login by default on new accounts, which the guide didn't mention because it's a pretty recent change on their end.

I ended up switching to a different login method (OAuth) instead, which took some trial and error too — at one point I had literally copied the wrong password into my code without realizing it.

So really, the hardest part was just staying patient through a lot of "why isn't this working" moments that turned out to have small, fixable causes once I actually looked closely at the error messages instead of just retrying the same thing.

## What would I improve with more time?

- Right now my code logs into ServiceNow fresh every single time it needs to update a ticket. That's wasteful — I'd make it reuse the same login for a while instead of asking every time.
- If Gemini or ServiceNow has a hiccup and fails once, my ticket just gets skipped with an error. I'd add a simple "try again" step so one bad moment doesn't lose the ticket completely.
- My duplicate-ticket check only lives in memory, so if I restart the service it forgets everything. I'd save that somewhere permanent instead.
- I'd test the AI prompt against more tricky example tickets, since I noticed early on it sometimes answered more confidently than expected on vague tickets.
