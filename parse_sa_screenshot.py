from PIL import Image
import pytesseract

img = Image.open('screenshots/SA_YJMLCC_status.png')
text = pytesseract.image_to_string(img)
print(text[:1000])
