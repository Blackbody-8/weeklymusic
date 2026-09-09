# Setting up Weekly Music Drop

Everything code-related is already written. What's left is account setup —
things only you can do since they need your logins. About 15–20 minutes total.

## 1. Create the GitHub repo

1. Go to github.com → New repository.
2. Name it whatever you like (e.g. `weekly-music-drop`). Public repo (GitHub
   Pages on the free tier needs a public repo, unless you're on GitHub Pro).
3. Upload every file in this folder to the repo, keeping the folder structure
   (`data/`, `archive/`, plus the loose files) — easiest is drag-and-drop on
   the repo's "Add file → Upload files" page, or GitHub Desktop if you have
   it installed.
   - Do **not** upload `secrets_config.py.example` renamed to the real thing —
     the real secrets file only ever lives on PythonAnywhere (step 5).
4. Repo → Settings → Pages → under "Build and deployment", set Source to
   "Deploy from a branch", branch `main`, folder `/ (root)`. Save.
5. GitHub will give you a URL like `https://yourusername.github.io/weekly-music-drop/`.
   That's your live site (it'll just show the "check back Friday" placeholder
   until the first run).

## 2. Get a Gemini API key

1. Go to aistudio.google.com/apikey (Google AI Studio).
2. Create an API key. Copy it somewhere safe for a moment — you'll paste it
   into `secrets_config.py` in step 5.

## 3. Get a GitHub token

1. GitHub → your profile photo → Settings → Developer settings →
   Personal access tokens → Fine-grained tokens → Generate new token.
2. Repository access: "Only select repositories" → pick your new repo.
3. Permissions → Repository permissions → Contents → set to "Read and write".
4. Generate, then copy the token (starts with `github_pat_...`). GitHub only
   shows it once.

## 4. Set up PythonAnywhere

1. Sign up free at pythonanywhere.com if you don't already have an account
   (sounds like you do, for SmartResumeFormat).
2. Open a Bash console from the Dashboard.
3. Clone your repo:
   ```
   git clone https://github.com/yourusername/weekly-music-drop.git
   ```
4. Install the one dependency:
   ```
   pip install --user requests
   ```

## 5. Add your secrets

Still in the Bash console:
```
cd weekly-music-drop
cp secrets_config.py.example secrets_config.py
nano secrets_config.py
```
Paste in your real Gemini key, GitHub token, and `yourusername/weekly-music-drop`
as `GITHUB_REPO`. Save (Ctrl+O, Enter, Ctrl+X in nano).

## 6. Test it once by hand

```
python3 weekly_update.py
```
It should print progress lines and end with "Done." Then check your GitHub
Pages URL — it should show a real week of music now.

If it errors, the message will say what failed (bad API key, wrong repo name,
etc.) — fix `secrets_config.py` and rerun.

## 7. Schedule it to run every Friday

1. PythonAnywhere Dashboard → Tasks tab.
2. Add a new scheduled task, set the time (PythonAnywhere runs tasks in UTC —
   pick a time that lands on Friday for you, accounting for the offset).
3. Command:
   ```
   python3 /home/YOURUSERNAME/weekly-music-drop/weekly_update.py
   ```
   (replace `YOURUSERNAME` with your actual PythonAnywhere username)
4. Free accounts get one always-on daily task slot — a weekly task fits
   comfortably within that.

That's it — from here it runs itself. Each Friday it'll ask Gemini, rebuild
the site, and push straight to GitHub, which republishes the Pages site
automatically within a minute or two.

## If you want a custom domain later

Same pattern as smartresumeformat.com — A records + CNAME through your DNS
provider pointing at GitHub Pages, then set the custom domain in the repo's
Pages settings.
