import datetime
import os
from execute import execute
import requests
import dateutil
import subprocess


git = os.environ.get("GIT", "git")

installed_commit_hash = None
installed_commit_ts = None
latest_commit_hash = None
latest_commit_ts = None


def _get_commit_hash(cwd=None):
    return execute([git, "rev-parse", "HEAD"], cwd=cwd)


def _get_commit_date(cwd=None):
    return execute([git, "show", "-s", "--format=%ci", "HEAD"])


def _get_remote_repo(cwd=None):
    remoteUrl = execute([git, "config", "--get", "remote.origin.url"])
    remoteUrlSplit = remoteUrl.split("/")
    if len(remoteUrlSplit) < 2:
        raise Exception(f"Invalid git repository remote origin url: {remoteUrl}")
    for i, r in enumerate(remoteUrlSplit):
        if r[-4:] == ".git":
            remoteUrlSplit[i] = r[:-4]
    return "/".join(remoteUrlSplit[-2:])


def _get_current_branch():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error getting current branch: {e.stderr.strip()}")

def _get_latest_commit(branch=None):
    repo = _get_remote_repo()
    if not branch:
        branch = _get_current_branch()
    response = requests.get(
        f"https://api.github.com/repos/{repo}/branches/{branch}"
    )

    if response.status_code == 200:
        commits = response.json()
        return commits["commit"]["sha"], commits["commit"]["commit"]["author"]["date"]
    else:
        raise ValueError(f"Error fetching commits from branch '{branch}': {response.status_code}")


def version_check():
    """
    Compare local git repo commit hash to latest commit hash on github
    """
    global installed_commit_ts, installed_commit_hash, latest_commit_hash, latest_commit_ts
    try:
        installed_commit_hash = _get_commit_hash()
        installed_commit_ts = _get_commit_date()
    except Exception as e:
        if e.args[1] == 128:
            print("WARNING: Can't check version. Not inside a git repository")
            return

        print("WARNING: Error getting commit hash during update check: ", e)
        return

    try:
        latest_commit_hash, latest_commit_ts = _get_latest_commit()
    except Exception as e:
        print("WARNING: Error getting latest remote commit hash: ", e)

    installed_commit_ts = dateutil.parser.parse(installed_commit_ts).astimezone(
        datetime.timezone.utc
    )
    latest_commit_ts = dateutil.parser.parse(latest_commit_ts).astimezone(
        datetime.timezone.utc
    )

    if latest_commit_hash == installed_commit_hash:
        print(
            f"Installed version ({installed_commit_hash[:7]}, {installed_commit_ts}) is up to date."
        )
    else:
        if latest_commit_ts > installed_commit_ts:
            print(
                f"NOTE: Installed version ({installed_commit_hash[:7]}, {installed_commit_ts}) is outdated. Run `git pull` to update to the latest version ({latest_commit_hash[:7]}, {latest_commit_ts})"
            )
        else:
            print(
                f"WARNING: Installed version ({installed_commit_hash[:7]}, {installed_commit_ts}) is newer than the latest master version ({latest_commit_hash[:7]}, {latest_commit_ts})."
            )
