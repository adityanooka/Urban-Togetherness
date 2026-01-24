# InvitingEnvironments


### Backend

Used: fastapi + python

To install: fastapi, python, pillow
(MacOS Terminal: brew install <package>; Windows: bib install <package>)
https://brew.sh

To run:
1. Check for respective directory
2. Create folder "static" in this directory
3. Add font of your preference to the directory and name it _font_for_printing.tff_

In bash: fastapi dev api_text_below_save.py

When API was susessfully called, it returns code 200

**@app.post("/process-image")**

@app.post("/process-image")
async def add_text_below(image: UploadFile = File(...), text: str = Form(...))

API receives an **image** and a **text**, rund locally by address 127.0.0.1

It takes original images and returns an image with the text added below.

UPDATES:

ERRORS:
edits an image and saves original and edited to /static. But does not retun a file somehow to the frontend (or frontend is stupid).
