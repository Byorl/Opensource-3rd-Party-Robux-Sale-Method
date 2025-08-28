# Roblox Gamepass → License Key Store

Sell time‑limited license keys automatically when someone buys a Roblox Gamepass.

Focus: make this super fast to set up. Copy the examples, swap placeholders, run.

---
## 1. What You Need
* Python 3.11+ (or 3.12)
* A PRIVATE GitHub repository that will just hold text files (your stock + logs)
* A Roblox .ROBLOSECURITY cookie (for reading recent transactions) – keep secret
* Gamepass IDs you will sell through

---
## 2. Create Your GitHub Stock Repo
Name it whatever you want (example: `MyHub-Keys`). Make it **private**.

Inside the repo create these empty files (capitalization matters):
```
Accounts
ClaimedTransactions
Keys Bought
Purchases

Stock/Your Product 7-Day Stock
Stock/Your Product 30-Day Stock
```
Add more `Stock/...` files for each duration / product you sell. (They can be empty; the code fills them.)

Keys in a stock file can be either format:
```
KEY1\nKEY2\nKEY3
```
or
```
["KEY1","KEY2"]
```

---
## 3. Copy & Fill `.env`
Open `config/.env.example`, copy contents into a new file named `config/.env` then change placeholders:
```
GITHUB_TOKEN=YOUR_GITHUB_TOKEN_HERE
GITHUB_REPO_OWNER=YOUR_GITHUB_USERNAME_HERE
GITHUB_REPO_NAME=YOUR_STOCK_REPO_NAME_HERE
GITHUB_BOUGHT_FILE=Keys-Bought
ADMIN_USERNAME=CHANGE_THIS_ADMIN_USERNAME
ADMIN_PASSWORD=CHANGE_THIS_ADMIN_PASSWORD
ROBLOX_SECURITY_COOKIE=YOUR_ROBLOSECURITY_COOKIE_HERE
PUBLIC_BASE_URL=http://localhost:5000
ALLOWED_ORIGINS=http://localhost:5000,http://127.0.0.1:5000
```
Later for production change the two last lines to your domain, e.g.:
```
PUBLIC_BASE_URL=https://store.example.com
ALLOWED_ORIGINS=https://store.example.com
```

---
## 4. Copy & Edit `products.json`
There is a template at `config/products.example.json`. Copy it to `config/products.json` and edit:
* `mainProducts[0].id` – a short id grouping variants
* For each entry in `products` set: `id`, `price`, `gamepassId`, `stockGithubFile` (exact file name you created under `Stock/`), and `duration`.
* `github.repo_owner` & `github.repo_name` MUST match your private repo.
* `settings.adminPanelRoute` – change to a random string; that's your admin panel page name.

Example minimal `products.json` (single product with 7 & 30 day):
```
{
  "mainProducts": [{
    "id": "myhub",
    "name": "My Hub",
    "description": "Premium access.",
    "mainImage": "https://placehold.co/64",
    "images": ["https://placehold.co/400x200"],
    "variants": ["7day","30day"]
  }],
  "products": [
    {"id": "my7","name": "My Hub 7D","price": 5,"gamepassId": "1234567","gamepassUrl": "https://www.roblox.com/game-pass/1234567/","description": "7 days","duration":"7 days","stockGithubFile":"My Hub 7-Day Stock","parentProduct":"myhub"},
    {"id": "my30","name": "My Hub 30D","price": 10,"gamepassId": "1234568","gamepassUrl": "https://www.roblox.com/game-pass/1234568/","description": "30 days","duration":"30 days","stockGithubFile":"My Hub 30-Day Stock","parentProduct":"myhub"}
  ],
  "github": {"repo_owner": "YOUR_GITHUB_USERNAME_HERE","repo_name": "YOUR_STOCK_REPO_NAME_HERE","bought_file": "Keys Bought"},
  "website": {"name": "My Store"},
  "settings": {"adminPanelRoute": "CHANGE_ME", "sse": {"sleepDefault":3,"sleepBurst":1}, "roblox": {"claimedFile":"ClaimedTransactions","transactionsLimit":25,"claimWindowHours":12,"preferSalesAPI":true}}
}
```

---
## 5. Install & Run
```
pip install -r requirements.txt
python server.py
```
Visit: `http://localhost:5000/index.html`

Admin panel URL: `http://localhost:5000/CHANGE_ME.html` (replace with your route).

Login using the admin credentials from `.env`.

---
## 6. Add Keys
Generate new keys + add to the right stock file:
```
python github_key_generator.py 25 my7
```
Bulk paste keys (one per line) into a product:
```
python bulk_add_keys.py --product my7
```
Status:
```
python github_key_generator.py status
```

---
## 7. How A Purchase Works
1. User buys your Roblox Gamepass.
2. They enter their Roblox username on the site.
3. Backend polls Roblox sale/ownership endpoints.
4. First unclaimed qualifying sale -> a key is popped from the matching stock file.
5. Key is recorded in `Keys Bought` and removed from stock.

If the same transaction is re-tried it will NOT issue another key.

---
## 8. Custom Domain
1. Point your domain to the server / reverse proxy.
2. Change `PUBLIC_BASE_URL` + `ALLOWED_ORIGINS` in `.env` to `https://yourdomain.com`.
3. Restart the server. Frontend auto-adjusts (paths are relative / config driven).

---
## 9. File Cheat Sheet
| File | Purpose |
|------|---------|
| server.py | Flask API + static serving |
| github_stock.py | GitHub file read/write helper |
| github_key_generator.py | Generate & push new keys |
| bulk_add_keys.py | Paste/import large key sets |
| config/products.json | Product + stock mapping |
| config/.env | Secrets + domain config |
| Stock/* | Raw key stock files per product |
| Keys Bought | Log of issued keys |

---
## 10. Security Tips
* Keep the GitHub repo PRIVATE.
* Never commit your real `.env`.
* Rotate the GitHub token if leaked.
* Use HTTPS in production.

---
## 11. Common Issues
| Problem | Fix |
|---------|-----|
| Empty products | Wrong repo owner/name/token |
| No key issued | Gamepass ID mismatch or no sale yet |
| CORS error | Update ALLOWED_ORIGINS |
| Duplicate keys skipped | This is normal (already existed) |
| Admin login fails | Check ADMIN_USERNAME / ADMIN_PASSWORD |

---
## 12. Formats Recap
Stock file accepted formats:
```
KEY1\nKEY2
```
or
```
["KEY1","KEY2"]
```

---
## 13. Next Ideas (Optional)
* Discord webhook on sale
* Rate limiting
* Expiration enforcement / auto-disable
* Docker deploy

---
License: MIT. Use responsibly.
