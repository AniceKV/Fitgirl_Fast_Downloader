## fetches all the fucking fast links for the given link
## read readme.md for usecase


import requests
from bs4 import BeautifulSoup
import sys

# get URL from terminal argument
url = sys.argv[1]

headers = {
    "User-Agent": "Mozilla/5.0"
}

res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, "html.parser")

links = []
for a in soup.find_all("a", href=True):
    if "fuckingfast.co" in a["href"]:
        links.append(a["href"])


with open(f"links.txt", "w") as f:
    for link in links:
        f.write(link + "\n")