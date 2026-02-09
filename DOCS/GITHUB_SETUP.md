# GitHub Setup Guide – Shoonya Trading Platform

This guide will help you push your Shoonya project to GitHub for synchronized development across EC2, Azure, local PCs, and other environments.

---

## Prerequisites

1. **GitHub Account**: Create one at https://github.com if you don't have one.
2. **Git Installed**: Ensure `git` is installed on your machine.
3. **SSH or HTTPS Credentials**: Set up authentication (recommended: SSH keys).

---

## Step 1: Create a New Repository on GitHub

1. Go to https://github.com/new
2. **Repository name**: `shoonya_platform` (or your preferred name)
3. **Description**: `Shoonya OMS – Trading Platform with Dashboard, Execution Engine, Risk Management`
4. **Visibility**: Choose **Private** (recommended for sensitive trading code) or **Public** if you want to share.
5. **Initialize**: Do **NOT** initialize with README, .gitignore, or license (we already have them).
6. Click **Create repository**.

---

## Step 2: Set Up SSH Keys (Recommended) or Use HTTPS

### Option A: SSH Keys (Recommended for automation)

1. **Check if you have SSH keys**:
   ```bash
   ls -la ~/.ssh
   ```
   If `id_rsa` and `id_rsa.pub` exist, skip to step 3.

2. **Generate SSH keys** (if needed):
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
   ```

3. **Add SSH key to GitHub**:
   - Copy your public key:
     ```bash
     cat ~/.ssh/id_rsa.pub
     ```
   - Go to GitHub → Settings → SSH and GPG keys → New SSH key
   - Paste the key and save.

4. **Test SSH connection**:
   ```bash
   ssh -T git@github.com
   ```
   You should see: `Hi <username>! You've successfully authenticated...`

### Option B: HTTPS (Simpler, but requires token)

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click **Generate new token (classic)**.
3. Select scopes: `repo`, `admin:repo_hook`, `workflow`.
4. **Copy the token** and store it securely (you'll use it as password for `git push`).

---

## Step 3: Push Your Project to GitHub

Run these commands in your project root (`C:\Users\gaura\OneDrive\Desktop\shoonya\shoonya_platform`):

### For SSH (Recommended):
```bash
git remote add origin git@github.com:<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
git branch -M main
git push -u origin main
```

### For HTTPS:
```bash
git remote add origin https://github.com/<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
git branch -M main
git push -u origin main
```

**Replace `<YOUR_USERNAME>` and `<YOUR_REPO_NAME>` with your actual GitHub username and repository name.**

You will be prompted to authenticate:
- **SSH**: Should authenticate automatically if keys are set up.
- **HTTPS**: Enter your GitHub username and paste the personal access token as the password.

---

## Step 4: Verify Upload

1. Go to your GitHub repository URL: `https://github.com/<YOUR_USERNAME>/<YOUR_REPO_NAME>`
2. You should see all your project files (excluding `env/` folder due to `.gitignore`).
3. Verify the commit: Click on the commit hash or "1 commit" link to see the initial commit.

---

## Step 5: Clone & Use on Other Machines (EC2, Azure, PC, etc.)

### On a new machine (EC2, Azure, or another PC):

```bash
# Clone the repository
git clone git@github.com:<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
# or for HTTPS:
git clone https://github.com/<YOUR_USERNAME>/<YOUR_REPO_NAME>.git

# Navigate to the project
cd shoonya_platform

# Create and activate virtual environment
python -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Step 6: Daily Development Workflow

### Commit and push changes:
```bash
# Make your changes, then:
git add .
git commit -m "Description of changes (e.g., 'Fix dashboard autocomplete bug')"
git push origin main
```

### Pull latest changes (before starting work):
```bash
git pull origin main
```

### Create a feature branch (optional but recommended):
```bash
git checkout -b feature/your-feature-name
# ... make changes ...
git add .
git commit -m "Add new feature"
git push -u origin feature/your-feature-name
# Create a Pull Request on GitHub to merge into main
```

---

## Step 7: Automated Sync Across Environments

To avoid manual sync, set up Git hooks or use CI/CD pipelines:

### Simple Auto-Sync (for development):

**On EC2 or any server, add a cron job** (every 10 minutes):
```bash
# Edit crontab
crontab -e

# Add this line:
*/10 * * * * cd /path/to/shoonya_platform && git pull origin main >> /tmp/shoonya_sync.log 2>&1
```

### GitHub Actions (Advanced – Automated Testing & Deployment):

1. Create `.github/workflows/tests.yml` in your repo:
```yaml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - run: pip install -r requirements.txt
      - run: pytest shoonya_platform/tests/ --tb=short -q
```

2. Commit and push:
```bash
git add .github/
git commit -m "Add GitHub Actions CI/CD"
git push origin main
```

Every push will automatically run your tests!

---

## Step 8: Ignoring Sensitive Data

Your `.gitignore` already excludes:
- `env/` – Virtual environment
- `*.env` – Environment files with credentials
- `logs/` – Log files
- `cookies.txt` – Session cookies
- `__pycache__/` – Python cache

**Before pushing sensitive data, always check**:
```bash
git status
```

If you accidentally commit secrets, use:
```bash
git rm --cached <file>
# Add the file to .gitignore
git add .gitignore <file>
git commit -m "Remove sensitive file from history"
git push origin main
```

---

## Step 9: Troubleshooting

### "fatal: remote origin already exists"
```bash
git remote remove origin
# Then re-add with the correct URL
git remote add origin git@github.com:<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
```

### "Permission denied (publickey)"
- Ensure SSH keys are set up correctly (Step 2A).
- Check `ssh -T git@github.com` returns a success message.

### "fatal: 'origin' does not appear to be a 'git' repository"
```bash
git remote -v  # Check current remotes
git remote add origin git@github.com:<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
```

### Large files in history
If you included large files (like backups):
```bash
git log --all --oneline --graph  # View history
# Use git-filter-branch or BFG to clean history (advanced)
```

---

## Step 10: Team Collaboration (Optional)

If you want teammates to access the repo:

1. Go to GitHub → Your Repo → Settings → Collaborators
2. Click "Add people" and enter their GitHub username.
3. They'll receive an invitation.
4. They can then clone the repo and follow the workflow in Step 5.

---

## Quick Reference

| Task | Command |
|------|---------|
| Clone repo | `git clone git@github.com:<user>/<repo>.git` |
| Check status | `git status` |
| Commit changes | `git commit -m "message"` |
| Push to GitHub | `git push origin main` |
| Pull latest | `git pull origin main` |
| Create branch | `git checkout -b feature/name` |
| View log | `git log --oneline` |
| Sync across machines | `git pull origin main` (on each machine) |

---

## Summary

✅ **Project is now Git-enabled and ready for GitHub!**

1. Create GitHub repo (Step 1)
2. Set up authentication (Step 2)
3. Push to GitHub (Step 3)
4. Clone on other machines (Step 5)
5. Use daily workflow (Step 6)
6. Optional: Set up CI/CD (Step 7)

From now on, any changes you commit and push will be automatically synced across all your machines without manual updates. Happy coding! 🚀

