name: Weekly Music Drop

on:
  schedule:
    # Runs every Friday at 13:00 UTC (6am Pacific during daylight saving;
    # 5am Pacific once the clocks fall back in November).
    - cron: "0 13 * * 5"
  workflow_dispatch:  # the "Run workflow" button on the Actions tab
    inputs:
      week_end:
        description: "Leave blank for the current week. To repair an older week, enter its Friday as YYYY-MM-DD."
        required: false
        default: ""

permissions:
  contents: write  # lets the script commit updated pages back to this repo

jobs:
  update-site:
    runs-on: ubuntu-latest
    steps:
      - name: Check out the repo
        uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run the weekly update
        run: python3 weekly_update.py
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
          GITHUB_BRANCH: main
          WEEK_END: ${{ inputs.week_end }}
