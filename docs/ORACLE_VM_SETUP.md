# Oracle Cloud Always Free VM — setup notes

Written ahead of phase 8 (deployment). Development through phase 7 happens locally; this is here so signup — which can take several attempts — can happen in parallel rather than blocking deployment later.

## What you're aiming for

The **Always Free** tier's ARM-based **Ampere A1** compute shape:

- Up to **4 OCPUs and 24 GB RAM** total, split across up to 4 instances (a single 4-OCPU/24GB instance is the simplest choice for this project — one box runs everything).
- Up to **200 GB** of block storage (boot + block volumes combined), Always Free.
- One **Always Free** outbound public IP.
- Two Always Free AMD micro-instances also exist (1 OCPU/1GB each) — not enough RAM for this app; ignore them.

This is genuinely free indefinitely (not a time-limited trial), as long as usage stays within the Always Free shape limits.

## Known friction points during signup

Oracle's free-tier signup has a reputation for being harder than it should be. Expect some or all of:

1. **Card verification failures.** Oracle authorizes a small refundable hold on a debit/credit card. International cards (especially some Indian bank cards) intermittently fail this even when valid — retrying, or trying a different card/bank, often works on a second attempt.
2. **"Out of capacity" for Ampere A1 in your chosen region.** Always Free A1 capacity is genuinely constrained in popular regions. If you hit this:
   - Try a different **Availability Domain** within the same region (some tenancies have 3 ADs; capacity often differs between them).
   - Try again at a different time of day — capacity frees up as other free-tier instances get reaped for inactivity.
   - Consider a nearby region if your data residency needs allow it (e.g. Mumbai vs Hyderabad for India).
3. **Account flagged for manual review.** Occasionally signups get held for identity verification. This is normal, not a rejection — it typically resolves within a day or two.
4. **Home region lock-in.** Whichever region you pick during signup becomes your tenancy's "home region" and is where Always Free resources must live. Choose deliberately (e.g. Mumbai for lowest latency to NSE/BSE, though this app's data fetches are not latency-sensitive since everything is EOD batch or 15-minute-delayed).

**If signup keeps failing:** it's a known, common experience, not something being done wrong. Retrying over a few days, trying a different card, and trying a different AD/region are the standard mitigations.

## Provisioning the instance (once signup succeeds)

1. **Create the instance:** Compute → Instances → Create. Choose:
   - Image: **Ubuntu 24.04 LTS (ARM64)** — Ubuntu has the best-tested ARM wheel availability for the Python packages this project uses (duckdb, pyarrow, pydantic-core).
   - Shape: **VM.Standard.A1.Flex**, 4 OCPU / 24 GB (the full Always Free allocation, if using it as a single instance).
   - Boot volume: 100 GB is comfortable (15 years of price history is ~200MB; the rest is OS + logs + headroom).
   - Add your SSH public key during creation.
2. **Networking:** the default VCN's default security list only opens SSH (22) inbound. Add ingress rules for **80** and **443** (Caddy will handle HTTP→HTTPS redirect and Let's Encrypt) once you're ready to expose the app. Keep everything else closed — this is a personal single-user app with no need for other open ports.
3. **A public DNS name** pointed at the instance's public IP is needed before Caddy can get a Let's Encrypt certificate (any free dynamic-DNS or a cheap domain works).

## Swap (important on ARM Always Free)

24GB RAM is generous for this app, but add a swap file anyway as a safety net against a runaway process (e.g. an fussy pandas operation during backfill) taking the whole box down:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## What phase 8 will set up on this box

(Not done yet — recorded here so the provisioning above is done with the end state in mind.)

- **uv** + the same `uv sync --all-groups` this repo uses locally, for identical dependency resolution (this is why `requires-python` is pinned tight in `pyproject.toml`).
- A **systemd timer** for `stk ingest daily` (nightly, after both exchanges publish bhavcopy).
- A **systemd service** for the intraday playground poller (phase 5), active only 9:15-15:30 IST on trading days.
- **Caddy** as the reverse proxy + automatic HTTPS in front of the FastAPI app (phase 4+).
- A backup routine for `data/app.db` (SQLite) and `data/parquet/` — both are the only state that matters; everything else is reproducible from `data/raw/` or from re-running ingest.

## Verifying capacity/ARM compatibility for Python deps now (optional, can do anytime)

If you want to de-risk the ARM wheel question before phase 8, the packages most likely to have ARM64 wheel gaps are `duckdb`, `pyarrow`, and `curl_cffi`. All three publish `manylinux_aarch64` wheels on PyPI as of the versions pinned in `backend/pyproject.toml` (uv resolved them without a source build in this project's development environment), so this is a low risk — but re-confirm with `uv sync` on the actual VM once it exists, since wheel availability can lag for brand-new releases.
