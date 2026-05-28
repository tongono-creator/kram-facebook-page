# merge_history.py — Safe conflict-free merging of bot history files in GitHub Actions
import os
import subprocess

HISTORY_FILES = ["posted_history.txt", "posted_photos.txt", "posted_recipes.txt", "replied_comments.txt"]

def main():
    # Find which files have local modifications
    modified_files = []
    for f in HISTORY_FILES:
        if os.path.exists(f):
            # Check if git detects modifications
            res = subprocess.run(["git", "diff", "--quiet", f])
            if res.returncode != 0:
                modified_files.append(f)

    if not modified_files:
        print("No history files modified. Exiting.")
        return

    print(f"Modified history files detected: {modified_files}")

    # Read and store local contents
    local_contents = {}
    for f in modified_files:
        with open(f, "r", encoding="utf-8") as file:
            local_contents[f] = [line.strip() for line in file if line.strip()]

    # Revert local changes to avoid merge conflicts during pull
    for f in modified_files:
        subprocess.run(["git", "checkout", "--", f])

    # Pull latest changes using rebase
    print("Pulling latest changes from git...")
    subprocess.run(["git", "pull", "--rebase"])

    # Merge remote and local contents
    for f in modified_files:
        remote_lines = []
        if os.path.exists(f):
            with open(f, "r", encoding="utf-8") as file:
                remote_lines = [line.strip() for line in file if line.strip()]

        local_lines = local_contents[f]
        # Merge remote first, then local (keeping unique items)
        merged = remote_lines + [line for line in local_lines if line not in remote_lines]
        
        # Cap size depending on file type
        if f == "replied_comments.txt":
            merged = merged[-1000:]
        else:
            merged = merged[-500:]

        with open(f, "w", encoding="utf-8") as file:
            for line in merged:
                file.write(line + "\n")

        # Stage the updated file
        subprocess.run(["git", "add", f])

    # Commit and push
    print("Staging and pushing merged history...")
    subprocess.run(["git", "commit", "-m", "chore: update history files [skip ci]"])
    subprocess.run(["git", "push"])

if __name__ == "__main__":
    main()
