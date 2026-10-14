# Running Agent HQ when the Mac is off

The office is a Python process plus a SQLite file. Wherever that process runs, the phone app
controls it. Three free options, from simplest to most independent.

## 1. Mac stays on, phone controls it from anywhere (today)

`./office/launchd/install.sh` already keeps the Mac awake on mains power with the lid closed.
Expose the dashboard securely with a free tunnel:

```bash
# quick tunnel, no account, URL changes each time it starts:
cloudflared tunnel --url http://localhost:8787
# -> prints https://<random>.trycloudflare.com ; open /m on the phone, enter the DASHBOARD_TOKEN from .env
```

For a stable address, either:
- **Tailscale** (free personal plan): install on Mac and phone, then `tailscale serve 8787` gives a
  private HTTPS URL that only your devices can reach. Most secure, no public exposure at all.
- **Cloudflare named tunnel** (free account + a domain you own, e.g. pribinkbenny.com):
  `cloudflared tunnel login && cloudflared tunnel create hq && cloudflared tunnel route dns hq hq.pribinkbenny.com`
  then `cloudflared tunnel run --url http://localhost:8787 hq`. Permanent URL: https://hq.pribinkbenny.com

The dashboard requires the token for every request that does not come from the Mac itself, so a
tunnel does not expose the office to the internet without the password. Web push notifications need
HTTPS, which both tunnels provide.

## 2. Free cloud VM (Mac truly off)

Oracle Cloud "Always Free" (ARM VM, 4 cores, 24 GB, no time limit) or Google Cloud e2-micro.
Both ask for a card for identity verification but the free tier is not charged.

```bash
# on the VM (Ubuntu):
sudo apt-get install -y docker.io git && sudo usermod -aG docker $USER
git clone https://github.com/PRIBINKBENNY/agent-hq-dev.git && cd agent-hq-dev
cp .env.example .env && nano .env            # keys + DASHBOARD_TOKEN
docker build -t agent-hq . && docker run -d --restart=always --name agent-hq -p 8787:8787 --env-file .env \
  -v agenthq-brain:/app/brain/data -v agenthq-workspace:/app/workspace -v agenthq-logs:/app/office/logs agent-hq
gh auth login                                 # once, for git_push from inside the container: mount ~/.config/gh
```

Then put a tunnel (same as option 1) or Tailscale on the VM. No Ollama on the VM: the provider pool
(Cerebras, Groq, Mistral, Gemini) does all inference; if every free tier is cooling down the run waits.

Moving the brain: copy `brain/data/brain.db` into the `agenthq-brain` volume once; after that the VM
is the single source of truth and the Mac becomes just another client of the phone app's URL.

## 3. Both (Mac during the day, VM at night)

Not recommended: two brains drift. Pick one home for the office.

## The phone app

Open `https://<your-url>/m` in Safari, Share → Add to Home Screen. It installs as "Agent HQ" with
an icon, runs full screen, shows approvals (approve / reject / I applied / view file), the task
board, today's digest, the scorecard, a live feed, voice commands, and push notifications for
approvals and finished tasks (iOS 16.4+, after tapping "Enable notifications" inside the installed app).
