Produce ONLY valid JSON, no commentary, conforming to these constraints:
{"username": string (lowercase, no spaces), "role": one of ["admin","editor","viewer"], "active": boolean, "login_count": integer >= 0}
Data: A user called "Sam Vega" who is an editor, currently active, has logged in 12 times. Convert the username to a valid lowercase form with no spaces.
