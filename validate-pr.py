#!/usr/bin/env python3
"""
Dataform PR Validation Script
Validates changes before creating a Pull Request to the dev branch
"""

import subprocess
import sys
import os
import re
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict


# Validation results tracking
class ValidationResults:
    """Tracks validation results across all checks"""
    def __init__(self):
        self.checks = []
        self.failed_checks = []
    
    def add_check(self, name: str, status: str, message: str = ""):
        """Add check result"""
        self.checks.append({
            'name': name,
            'status': status,  # 'pass', 'fail', 'warn', 'skip'
            'message': message
        })
        if status == 'fail':
            self.failed_checks.append(f"{name}: {message}")
    
    def has_failures(self) -> bool:
        """Check if any validation failed"""
        return len(self.failed_checks) > 0
    
    def get_failure_count(self) -> int:
        """Get number of failed checks"""
        return len(self.failed_checks)


class Colors:
    """ANSI color codes for terminal (works on Windows 10+)"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color
    BOLD = '\033[1m'


def print_header(text: str):
    """Prints formatted header"""
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.NC}")
    print(f"{Colors.BOLD}{text:^60}{Colors.NC}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.NC}\n")


def print_success(text: str):
    """Prints success message"""
    print(f"{Colors.GREEN}✅ {text}{Colors.NC}")


def print_error(text: str):
    """Prints error message"""
    print(f"{Colors.RED}❌ {text}{Colors.NC}")


def print_warning(text: str):
    """Prints warning message"""
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.NC}")


def run_command(cmd: List[str], check: bool = True, cwd: str = None) -> Tuple[int, str, str]:
    """
    Executes command and returns exit code, stdout and stderr
    
    Args:
        cmd: List with command and arguments
        check: If True, raises exception on error
        cwd: Working directory for command execution (optional)
    
    Returns:
        Tuple (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=cwd
        )
        
        if check and result.returncode != 0:
            print_error(f"Command failed: {' '.join(cmd)}")
            if result.stderr:
                print(result.stderr)
            sys.exit(result.returncode)
        
        return result.returncode, result.stdout, result.stderr
    
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Error executing command: {e}")
        sys.exit(1)


def get_current_branch() -> str:
    """Gets the current branch name"""
    _, stdout, _ = run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
    return stdout.strip()


def fetch_target_branch(target_branch: str):
    """Fetches the target branch"""
    print(f"Fetching origin/{target_branch}...")
    run_command(['git', 'fetch', 'origin', target_branch])


def check_branch_freshness(target_branch: str) -> Tuple[int, int, bool]:
    """
    Checks how many commits the current branch is ahead/behind target
    and detects potential merge conflicts
    
    Args:
        target_branch: Target branch name
    
    Returns:
        Tuple (commits_ahead, commits_behind, has_conflicts)
    """
    print(f"{Colors.BOLD}Check 1: Branch freshness and merge conflicts{Colors.NC}")
    print()
    
    # Count commits ahead and behind
    _, ahead_str, _ = run_command([
        'git', 'rev-list', '--count', f'origin/{target_branch}..HEAD'
    ], check=False)
    
    _, behind_str, _ = run_command([
        'git', 'rev-list', '--count', f'HEAD..origin/{target_branch}'
    ], check=False)
    
    commits_ahead = int(ahead_str.strip()) if ahead_str.strip() else 0
    commits_behind = int(behind_str.strip()) if behind_str.strip() else 0
    
    print("Branch status:")
    print(f"  Commits ahead of {target_branch}: {Colors.BLUE}{commits_ahead}{Colors.NC}")
    print(f"  Commits behind {target_branch}: {Colors.BLUE}{commits_behind}{Colors.NC}")
    print()
    
    # Warn if significantly behind
    BEHIND_THRESHOLD = 10
    if commits_behind > BEHIND_THRESHOLD:
        print_warning(f"Branch is {commits_behind} commits behind {target_branch}")
        print(f"{Colors.YELLOW}   Recommendation: Rebase or merge to ensure compatibility{Colors.NC}")
        print()
    
    # Check for merge conflicts by attempting dry-run merge
    print("Checking for merge conflicts...")
    
    # Save current HEAD
    _, original_head, _ = run_command(['git', 'rev-parse', 'HEAD'])
    original_head = original_head.strip()
    
    has_conflicts = False
    
    try:
        # Attempt merge (no-commit)
        exit_code, stdout, stderr = run_command([
            'git', 'merge', '--no-commit', '--no-ff', f'origin/{target_branch}'
        ], check=False)
        
        if exit_code != 0:
            # Merge failed - conflicts detected
            has_conflicts = True
            
            # Get conflicting files (try multiple methods)
            _, conflicting_files, _ = run_command([
                'git', 'diff', '--name-only', '--diff-filter=U'
            ], check=False)
            
            # Fallback: use ls-files --unmerged
            if not conflicting_files.strip():
                _, unmerged, _ = run_command([
                    'git', 'ls-files', '--unmerged', '--format=%(path)'
                ], check=False)
                if unmerged.strip():
                    # Deduplicate (ls-files lists each stage separately)
                    conflicting_files = '\n'.join(sorted(set(unmerged.strip().split('\n'))))
            
            # Fallback: parse stderr for conflict hints
            if not conflicting_files.strip() and stderr:
                conflict_lines = [
                    line.strip().replace('CONFLICT (content): Merge conflict in ', '')
                    for line in stderr.split('\n')
                    if 'CONFLICT' in line and 'Merge conflict in' in line
                ]
                if conflict_lines:
                    conflicting_files = '\n'.join(conflict_lines)
            
            print_error("Merge conflicts detected!")
            print()
            if conflicting_files.strip():
                print("Conflicting files:")
                for file in conflicting_files.strip().split('\n'):
                    if file.strip():
                        print(f"  {Colors.RED}• {file.strip()}{Colors.NC}")
            else:
                print(f"{Colors.YELLOW}Could not determine conflicting files.{Colors.NC}")
                print(f"Run manually: git merge origin/{target_branch}")
            print()
            
            # Abort merge
            run_command(['git', 'merge', '--abort'], check=False)
            
            print(f"{Colors.YELLOW}Action required:{Colors.NC}")
            print(f"  1. Update your branch: git fetch origin {target_branch}")
            print(f"  2. Merge or rebase: git merge origin/{target_branch}")
            print("  3. Resolve conflicts and try again")
            print()
            
            return commits_ahead, commits_behind, has_conflicts
        
        # Merge successful - check what would be merged
        _, merged_files, _ = run_command([
            'git', 'diff', '--cached', '--name-only'
        ], check=False)
        
        # Check if includes/ folder would be updated
        if 'includes/' in merged_files:
            print(f"{Colors.BLUE}ℹ️  Merge would update shared code (includes/ folder){Colors.NC}")
            print("   Dataform compilation will use latest versions")
            print()
        
        # Abort merge (we just wanted to check)
        run_command(['git', 'merge', '--abort'], check=False)
        
        print_success("No merge conflicts detected")
        
    except Exception as e:
        # Clean up
        run_command(['git', 'merge', '--abort'], check=False)
        print_error(f"Error checking merge conflicts: {e}")
        has_conflicts = True
    
    return commits_ahead, commits_behind, has_conflicts


def get_changed_files(target_branch: str) -> List[str]:
    """
    Gets list of changed files compared to target branch
    
    Args:
        target_branch: Target branch name
    
    Returns:
        List of changed file paths
    """
    _, stdout, _ = run_command([
        'git', 'diff', '--name-only', 
        f'origin/{target_branch}...HEAD'
    ])
    
    files = [f.strip() for f in stdout.split('\n') if f.strip()]
    return files


def check_files_in_definitions(changed_files: List[str]) -> bool:
    """
    Checks if all changed files are in definitions/
    
    Args:
        changed_files: List of changed files
    
    Returns:
        True if all files are in definitions/, False otherwise
    """
    print(f"{Colors.BOLD}Check 2: Verifying changes are only in definitions/{Colors.NC}")
    print()
    
    if not changed_files:
        print_warning("No changes detected")
        return True
    
    print("Changed files:")
    for file in changed_files:
        print(f"  {file}")
    print()
    
    # Check for files outside definitions/
    invalid_files = [f for f in changed_files if not f.startswith('definitions/')]
    
    if invalid_files:
        print_error("Files outside definitions/ folder detected:")
        for file in invalid_files:
            print(f"  {Colors.RED}{file}{Colors.NC}")
        print()
        
        # Check if files are in code_generation/ (common mistake)
        code_gen_files = [f for f in invalid_files if f.startswith('code_generation/')]
        if code_gen_files:
            print(f"{Colors.YELLOW}💡 Note: Files in code_generation/ are NOT compiled by Dataform{Colors.NC}")
            print(f"{Colors.YELLOW}   Dataform only processes files under definitions/{Colors.NC}")
            print(f"{Colors.YELLOW}   If these are templates, move them to definitions/{Colors.NC}")
            print()
        
        return False
    
    print_success("All changes are within definitions/ folder")
    return True


def validate_folder_structure(changed_files: List[str]) -> bool:
    """
    Validates that all changed files follow the expected 3-level structure:
    Level 1: definitions
    Level 2: dimensions|facts
    Level 3: db*|dc*|fb*|fc*|fin*|lms* (project name)
    
    Args:
        changed_files: List of changed files
    
    Returns:
        True if all files follow expected structure, False otherwise
    """
    print(f"{Colors.BOLD}Check 2b: Validating folder structure{Colors.NC}")
    print()
    
    VALID_TYPES = {'dimensions', 'facts'}
    VALID_PREFIXES = ('db', 'dc', 'fb', 'fc', 'fin', 'lms')
    
    invalid_folders = {}  # folder -> reason
    
    for file in changed_files:
        if not file.startswith('definitions/'):
            continue
        
        parts = Path(file).parts
        
        # Must have at least 4 parts: definitions/type/project/file.sqlx
        if len(parts) < 4:
            folder = str(Path(*parts[:min(len(parts), 3)]))
            invalid_folders[folder] = "Insufficient path depth (need definitions/type/project/file)"
            continue
        
        # Extract folder (first 3 levels)
        folder = str(Path(parts[0]) / parts[1] / parts[2])
        
        # Skip if already marked as invalid
        if folder in invalid_folders:
            continue
        
        # Level 2: Must be dimensions or facts
        folder_type = parts[1]
        if folder_type not in VALID_TYPES:
            invalid_folders[folder] = f"Invalid folder type '{folder_type}' (expected: dimensions or facts)"
            continue
        
        # Level 3: Must start with valid prefix
        project_name = parts[2]
        if not any(project_name.startswith(prefix) for prefix in VALID_PREFIXES):
            invalid_folders[folder] = f"Invalid project name '{project_name}' (expected prefix: {', '.join(VALID_PREFIXES)})"
            continue
    
    if invalid_folders:
        print_error("Invalid folder structure detected:")
        for folder, reason in sorted(invalid_folders.items()):
            print(f"  {Colors.RED}{folder}{Colors.NC}")
            print(f"    → {reason}")
        print()
        
        # Check for common mistake: definitions/sqlx/type/project
        sqlx_folders = [f for f in invalid_folders.keys() if '\\sqlx\\' in str(f) or '/sqlx/' in str(f)]
        if sqlx_folders:
            print(f"{Colors.YELLOW}💡 Suggestion for sqlx folders:{Colors.NC}")
            for folder in sqlx_folders:
                parts = Path(folder).parts
                if len(parts) >= 3 and parts[1] == 'sqlx':
                    suggested = str(Path(parts[0]) / parts[2] / parts[3]) if len(parts) >= 4 else str(Path(parts[0]) / parts[2])
                    print(f"{Colors.YELLOW}   Move: {folder}/{Colors.NC}")
                    print(f"{Colors.YELLOW}     To: {suggested}/{Colors.NC}")
            print()
        
        print(f"{Colors.YELLOW}Expected structure:{Colors.NC}")
        print("  definitions/<dimensions|facts>/<db*|dc*|fb*|fc*|fin*|lms*>/<file>")
        print()
        print(f"{Colors.YELLOW}Examples:{Colors.NC}")
        print("  ✅ definitions/dimensions/db_customer/db_customer.sqlx")
        print("  ✅ definitions/facts/fb_sales/fb_sales.sqlx")
        print(f"  {Colors.RED}❌ definitions/sqlx/dimensions/db_customer.sqlx{Colors.NC}")
        print(f"  {Colors.RED}❌ definitions/dimensions/invalid_name/file.sqlx{Colors.NC}")
        return False
    
    print_success("All files follow expected folder structure")
    return True


def extract_changed_folders(changed_files: List[str]) -> Set[str]:
    """
    Extracts unique changed folders at project level (definitions/type/project)
    Only includes folders that follow the expected structure:
    - Level 2 must be: dimensions or facts
    - Level 3 must start with: db, dc, fb, fc, fin, lms
    
    Args:
        changed_files: List of changed files
    
    Returns:
        Set of changed project folders (e.g., 'definitions/dimensions/db_customer')
    """
    VALID_TYPES = {'dimensions', 'facts'}
    VALID_PREFIXES = ('db', 'dc', 'fb', 'fc', 'fin', 'lms')
    
    folders = set()
    
    for file in changed_files:
        if file.startswith('definitions/'):
            parts = Path(file).parts
            
            # Need at least: definitions/type/project/file
            if len(parts) < 4:
                continue
            
            folder_type = parts[1]
            project_name = parts[2]
            
            # Only extract folders with valid structure
            if folder_type in VALID_TYPES and any(project_name.startswith(prefix) for prefix in VALID_PREFIXES):
                folder = str(Path(parts[0]) / parts[1] / parts[2])
                folders.add(folder)
    
    return folders


def get_required_projects(changed_folders: Set[str]) -> List[str]:
    """
    Determines required projects based on changed folders
    
    Args:
        changed_folders: Set of changed folders
    
    Returns:
        List of project names (e.g., ['db_customer', 'db_postal_code'])
    """
    projects = []
    
    for folder in sorted(changed_folders):
        parts = Path(folder).parts
        
        # Extract project name from definitions/type/project structure
        if len(parts) >= 3:
            project_name = parts[2]  # 0=definitions, 1=dimensions/facts, 2=project
            projects.append(project_name)
    
    return projects


def get_commit_tags(commit: str = 'HEAD') -> List[str]:
    """
    Gets all Git tags pointing to a specific commit
    
    Args:
        commit: Commit reference (default: HEAD)
    
    Returns:
        List of tag names
    """
    exit_code, stdout, _ = run_command(
        ['git', 'tag', '--points-at', commit],
        check=False
    )
    
    if exit_code != 0 or not stdout:
        return []
    
    return [tag.strip() for tag in stdout.split('\n') if tag.strip()]


def parse_individual_tag(tag: str) -> Optional[Tuple[str, Tuple[int, int, int]]]:
    """
    Parses individual project tag
    Accepts v1, v1.0, or v1.0.0 formats (missing parts default to 0)
    
    Args:
        tag: Tag in format 'db_customer-v1[.2[.3]]'
    
    Returns:
        Tuple (project_name, (major, minor, patch)) or None
    
    Examples:
        >>> parse_individual_tag('db_customer-v1.2.3')
        ('db_customer', (1, 2, 3))
        >>> parse_individual_tag('db_customer-v1.2')
        ('db_customer', (1, 2, 0))
        >>> parse_individual_tag('db_customer-v1')
        ('db_customer', (1, 0, 0))
    """
    pattern = r'^([a-z_]+)-v(\d+)(?:\.(\d+))?(?:\.(\d+))?$'
    match = re.match(pattern, tag)
    
    if match:
        project = match.group(1)
        # Exclude reserved prefixes
        if project == 'release':
            return None
        major = int(match.group(2))
        minor = int(match.group(3)) if match.group(3) is not None else 0
        patch = int(match.group(4)) if match.group(4) is not None else 0
        return (project, (major, minor, patch))
    
    return None


def parse_release_tag(tag: str) -> Optional[Tuple[str, Tuple[int, int, int]]]:
    """
    Parses consolidated release tag
    Accepts v1, v1.0, or v1.0.0 formats (missing parts default to 0)
    
    Args:
        tag: Tag in format 'release-name-v1[.0[.0]]'
    
    Returns:
        Tuple (release_name, (major, minor, patch)) or None
    
    Examples:
        >>> parse_release_tag('release-customer-migration-v1.0.0')
        ('customer-migration', (1, 0, 0))
        >>> parse_release_tag('release-customer-migration-v2.1')
        ('customer-migration', (2, 1, 0))
        >>> parse_release_tag('release-hotfix-v3')
        ('hotfix', (3, 0, 0))
    """
    pattern = r'^release-(.+)-v(\d+)(?:\.(\d+))?(?:\.(\d+))?$'
    match = re.match(pattern, tag)
    
    if match:
        name = match.group(1)
        major = int(match.group(2))
        minor = int(match.group(3)) if match.group(3) is not None else 0
        patch = int(match.group(4)) if match.group(4) is not None else 0
        return (name, (major, minor, patch))
    
    return None


def check_required_tags(changed_folders: Set[str]) -> bool:
    """
    Validates Git tags for changed projects
    Hybrid approach:
    - 1 project: Requires 1 individual tag
    - N projects: Requires N individual tags + 1 consolidated release tag
    
    Args:
        changed_folders: Set of changed folders
    
    Returns:
        True if tags are valid, False otherwise
    """
    print(f"{Colors.BOLD}Check 3: Validating Git tags{Colors.NC}")
    print()
    
    if not changed_folders:
        print_warning("No valid folders changed")
        print(f"{Colors.BLUE}ℹ️  All changed files are in invalid folder structures{Colors.NC}")
        print(f"{Colors.BLUE}   Fix CHECK 2 and CHECK 2b errors first to enable tag validation{Colors.NC}")
        return True
    
    # Get required projects
    required_projects = get_required_projects(changed_folders)
    num_projects = len(required_projects)
    
    print(f"Changed projects ({num_projects}):")
    for project in required_projects:
        print(f"  - {project}")
    print()
    
    # Get tags on HEAD commit
    commit_tags = get_commit_tags('HEAD')
    
    if not commit_tags:
        print_error("No Git tags found on HEAD commit")
        print()
        print(f"{Colors.YELLOW}Required tags:{Colors.NC}")
        if num_projects == 1:
            print(f"  - {required_projects[0]}-v<MAJOR>.<MINOR>.<PATCH>")
            print()
            print(f"{Colors.BLUE}Example:{Colors.NC}")
            print(f"  git tag -a {required_projects[0]}-v1.0.0 -m 'Release v1.0.0'")
        else:
            print(f"  Individual tags (for audit):")
            for project in required_projects:
                print(f"    - {project}-v<MAJOR>.<MINOR>.<PATCH>")
            print(f"  Consolidated tag (for deployment):")
            print(f"    - release-<name>-v<MAJOR>.<MINOR>.<PATCH>")
            print()
            print(f"{Colors.BLUE}Example:{Colors.NC}")
            for project in required_projects:
                print(f"  git tag -a {project}-v1.0.0 -m 'Part of release'")
            print(f"  git tag -a release-my-feature-v1.0.0 -m 'Consolidated release'")
        print()
        print(f"{Colors.BLUE}Then push tags:{Colors.NC}")
        print(f"  git push origin --tags")
        return False
    
    print(f"Found tags on HEAD:")
    for tag in commit_tags:
        print(f"  - {tag}")
    print()
    
    # Parse tags
    individual_tags = {}
    release_tag = None
    
    for tag in commit_tags:
        parsed_individual = parse_individual_tag(tag)
        parsed_release = parse_release_tag(tag)
        
        if parsed_individual:
            project, version = parsed_individual
            individual_tags[project] = (tag, version)
        elif parsed_release:
            release_tag = tag
    
    # Validation logic
    if num_projects == 1:
        # Scenario 1: Single project - requires 1 individual tag
        project = required_projects[0]
        
        if project in individual_tags:
            tag_name, version = individual_tags[project]
            print_success(f"Valid tag found: {tag_name}")
            print(f"  Project: {project}")
            print(f"  Version: v{'.'.join(map(str, version))}")
            print()
            print(f"{Colors.GREEN}✅ Ready for deployment using: {tag_name}{Colors.NC}")
            return True
        else:
            print_error(f"Missing required tag for project: {project}")
            print()
            print(f"{Colors.YELLOW}Required:{Colors.NC}")
            print(f"  git tag -a {project}-v<MAJOR>.<MINOR>.<PATCH> -m 'Release'")
            return False
    else:
        # Scenario 2: Multiple projects - requires N individual + 1 release
        missing_projects = []
        
        print(f"Individual tags validation:")
        for project in required_projects:
            if project in individual_tags:
                tag_name, version = individual_tags[project]
                print(f"  ✅ {project}: {tag_name} (v{'.'.join(map(str, version))})")
            else:
                print(f"  ❌ {project}: Missing tag")
                missing_projects.append(project)
        print()
        
        if release_tag:
            print(f"Consolidated release tag: ✅ {release_tag}")
        else:
            print(f"Consolidated release tag: ❌ Missing")
        print()
        
        if missing_projects or not release_tag:
            print_error("Validation failed")
            print()
            if missing_projects:
                print(f"{Colors.YELLOW}Missing individual tags:{Colors.NC}")
                for project in missing_projects:
                    print(f"  git tag -a {project}-v<MAJOR>.<MINOR>.<PATCH> -m 'Part of release'")
                print()
            if not release_tag:
                print(f"{Colors.YELLOW}Missing consolidated tag:{Colors.NC}")
                print(f"  git tag -a release-<name>-v<MAJOR>.<MINOR>.<PATCH> -m 'Consolidated release'")
                print()
            print(f"{Colors.BLUE}Then push tags:{Colors.NC}")
            print(f"  git push origin --tags")
            return False
        
        print_success("All tags validated")
        print()
        print(f"{Colors.GREEN}✅ Ready for deployment using: {release_tag}{Colors.NC}")
        print()
        print(f"Individual tags (audit trail):")
        for project in required_projects:
            if project in individual_tags:
                tag_name, _ = individual_tags[project]
                print(f"  - {tag_name}")
        
        return True





def compare_versions(v1: Tuple[int, int, int], v2: Tuple[int, int, int]) -> int:
    """
    Compares two semantic versions
    
    Args:
        v1: Version 1 as (major, minor, patch)
        v2: Version 2 as (major, minor, patch)
    
    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2
    """
    if v1 < v2:
        return -1
    elif v1 > v2:
        return 1
    else:
        return 0


def get_target_branch_versions_from_tags(target_branch: str) -> Dict[str, Tuple[int, int, int]]:
    """
    Gets most recent Git Tag versions for each project in target branch
    
    Args:
        target_branch: Target branch name (e.g., 'dev')
    
    Returns:
        Dictionary {project: (major, minor, patch)} with highest version of each project
    """
    # Get all tags reachable from target branch
    exit_code, stdout, _ = run_command([
        'git', 'tag', '--merged', f'origin/{target_branch}'
    ], check=False)
    
    if exit_code != 0 or not stdout:
        return {}
    
    project_versions: Dict[str, Tuple[int, int, int]] = {}
    
    for tag in stdout.split('\n'):
        tag = tag.strip()
        if not tag:
            continue
        
        # Parse individual project tags only
        parsed = parse_individual_tag(tag)
        if parsed:
            project, version = parsed
            
            # Keep only highest version of each project
            if project not in project_versions:
                project_versions[project] = version
            else:
                if compare_versions(version, project_versions[project]) > 0:
                    project_versions[project] = version
    
    return project_versions


def check_version_conflicts_tags(commit_tags: List[str], target_branch: str) -> bool:
    """
    Validates that no tag version is lower than versions already in target branch
    Uses Git Tags instead of GitHub Labels
    
    Args:
        commit_tags: Git tags on HEAD commit
        target_branch: Target branch
    
    Returns:
        True if there are no version conflicts, False otherwise
    """
    print(f"{Colors.BOLD}Check 4: Validating semantic versioning{Colors.NC}")
    print()
    
    if not commit_tags:
        print_warning("No Git tags found on HEAD commit, skipping version validation")
        print(f"{Colors.BLUE}ℹ️  Version validation requires Git tags in format: db_customer-v1[.0[.0]]{Colors.NC}")
        return True
    
    # Parse individual project tags only
    project_versions: Dict[str, Tuple[int, int, int]] = {}
    
    print("Analyzing tags on HEAD commit:")
    for tag in commit_tags:
        parsed = parse_individual_tag(tag)
        if parsed:
            project, version = parsed
            project_versions[project] = version
            print(f"  ✅ {tag} → {project} v{'.'.join(map(str, version))}")
        else:
            # Skip release tags or invalid tags
            if tag.startswith('release-'):
                print(f"  ℹ️  {tag} (consolidated release tag, skipped)")
            else:
                print(f"  ⚠️  {tag} (invalid format, skipped)")
    
    if not project_versions:
        print()
        print_warning("No individual project tags found for version validation")
        return True
    
    print()
    print(f"Fetching existing versions from origin/{target_branch}...")
    
    # Get existing versions in target branch
    target_versions = get_target_branch_versions_from_tags(target_branch)
    
    if not target_versions:
        print_warning(f"No version history found in {target_branch}")
        print_success("All tag versions are acceptable (no conflicts possible)")
        return True
    
    print()
    print("Latest versions in target branch:")
    for project, version in sorted(target_versions.items()):
        print(f"  {project}: v{'.'.join(map(str, version))}")
    
    # Validate conflicts
    conflicts = []
    print()
    print("Version comparison:")
    
    for project, head_version in project_versions.items():
        if project in target_versions:
            target_version = target_versions[project]
            comparison = compare_versions(head_version, target_version)
            
            if comparison < 0:
                # HEAD version is LOWER than target branch version - CONFLICT!
                conflicts.append((project, head_version, target_version))
                print(f"  ❌ {project}: v{'.'.join(map(str, head_version))} < v{'.'.join(map(str, target_version))} {Colors.RED}(CONFLICT!){Colors.NC}")
            elif comparison == 0:
                print(f"  ⚠️  {project}: v{'.'.join(map(str, head_version))} = v{'.'.join(map(str, target_version))} {Colors.YELLOW}(same version){Colors.NC}")
            else:
                print(f"  ✅ {project}: v{'.'.join(map(str, head_version))} > v{'.'.join(map(str, target_version))} {Colors.GREEN}(OK){Colors.NC}")
        else:
            print(f"  ✅ {project}: v{'.'.join(map(str, head_version))} {Colors.GREEN}(new project){Colors.NC}")
    
    print()
    
    if conflicts:
        print_error("Version conflicts detected!")
        print()
        print("The following tag versions are OLDER than versions already in the target branch:")
        for project, head_version, target_version in conflicts:
            print(f"  {Colors.RED}• {project}: HEAD v{'.'.join(map(str, head_version))} < {target_branch} v{'.'.join(map(str, target_version))}{Colors.NC}")
        print()
        print(f"{Colors.YELLOW}Action required:{Colors.NC}")
        print("  1. Update your Git tags to higher version numbers, OR")
        print("  2. Rebase/merge the latest changes from the target branch")
        print()
        print(f"{Colors.BLUE}To delete and recreate a tag:{Colors.NC}")
        for project, _, _ in conflicts:
            print(f"  git tag -d {project}-v<old>")
            print(f"  git tag -a {project}-v<new> -m 'Release'")
            print(f"  git push origin :{project}-v<old>  # Delete remote")
            print(f"  git push origin {project}-v<new>")
        return False
    
    print_success("No version conflicts detected")
    return True


def compile_dataform() -> bool:
    """
    Compiles Dataform project using npx
    
    Returns:
        True if compilation was successful, False otherwise
    """
    print(f"{Colors.BOLD}Check 5: Compiling Dataform project{Colors.NC}")
    print()
    
    # Locate the Dataform project root by walking up from this script
    script_dir = Path(__file__).resolve().parent
    project_root = next(
        (d for d in [script_dir, *script_dir.parents] if (d / 'workflow_settings.yaml').exists()),
        None
    )
    
    if project_root is None:
        print_error("workflow_settings.yaml not found")
        print(f"{Colors.YELLOW}Searched from: {script_dir} upwards{Colors.NC}")
        return False
    
    # Determine correct npx command (Windows uses npx.cmd)
    npx_cmd = 'npx.cmd' if sys.platform == 'win32' else 'npx'
    
    # Check if npx is available
    exit_code, _, _ = run_command([npx_cmd, '--version'], check=False)
    if exit_code != 0:
        print_error("npx not found. Please install Node.js first.")
        print(f"{Colors.BLUE}Download: https://nodejs.org/{Colors.NC}")
        return False
    
    # Compile project from project root
    print(f"Running: {npx_cmd} -y @dataform/cli compile")
    print(f"Working directory: {project_root}")
    print()
    
    exit_code, stdout, stderr = run_command(
        [npx_cmd, '-y', '@dataform/cli', 'compile'],
        check=False,
        cwd=str(project_root)
    )
    
    if exit_code != 0:
        print_error("Compilation failed:")
        print()
        if stderr:
            print(stderr)
        if stdout:
            print(stdout)
        return False
    
    # Display compilation output
    print(stdout)
    
    # Check for errors in output (avoid matching table names containing "error")
    if re.search(r'^\s*Compilation errors?:', stdout, re.MULTILINE | re.IGNORECASE):
        print_error("Compilation completed with errors")
        return False
    
    print_success("Dataform compilation successful")
    
    return True


def print_validation_report(results: ValidationResults):
    """
    Prints consolidated validation report
    
    Args:
        results: ValidationResults object with all check results
    """
    print()
    print("=" * 60)
    print_header("VALIDATION RESULTS REPORT")
    print("=" * 60)
    print()
    
    # Display each check result
    for check in results.checks:
        status_icon = ""
        status_color = Colors.NC
        
        if check['status'] == 'pass':
            status_icon = "✅"
            status_color = Colors.GREEN
        elif check['status'] == 'fail':
            status_icon = "❌"
            status_color = Colors.RED
        elif check['status'] == 'warn':
            status_icon = "⚠️"
            status_color = Colors.YELLOW
        elif check['status'] == 'skip':
            status_icon = "⏭️"
            status_color = Colors.BLUE
        
        status_text = check['status'].upper()
        message_text = f" - {check['message']}" if check['message'] else ""
        
        print(f"{status_icon} {check['name']}: {status_color}{status_text}{Colors.NC}{message_text}")
    
    print()
    print("=" * 60)
    
    # Summary
    failure_count = results.get_failure_count()
    
    if failure_count > 0:
        print(f"{Colors.RED}❌ VALIDATION FAILED: {failure_count} check(s) failed{Colors.NC}")
        print()
        print("Failed checks:")
        for failure in results.failed_checks:
            print(f"  • {Colors.RED}{failure}{Colors.NC}")
    else:
        print(f"{Colors.GREEN}✅ ALL VALIDATIONS PASSED{Colors.NC}")
    
    print("=" * 60)
    print()


def print_summary(success: bool, target_branch: str, commits_ahead: int = 0, commits_behind: int = 0):
    """
    Prints final validation summary
    
    Args:
        success: If all validations passed
        target_branch: Target branch
        commits_ahead: Number of commits ahead of target branch
        commits_behind: Number of commits behind target branch
    """
    print_header("Validation Summary")
    
    if success:
        print_success("All local validations passed!")
        print()
        
        # Show branch status
        if commits_ahead > 0 or commits_behind > 0:
            print(f"{Colors.BOLD}Branch Status:{Colors.NC}")
            print(f"  • Commits ahead: {Colors.BLUE}{commits_ahead}{Colors.NC}")
            print(f"  • Commits behind: {Colors.BLUE}{commits_behind}{Colors.NC}")
            
            if commits_behind > 10:
                print()
                print(f"  {Colors.YELLOW}⚠️  Consider rebasing for better compatibility{Colors.NC}")
            print()
        
        print(f"{Colors.BOLD}Your branch is ready to merge into {Colors.BLUE}{target_branch}{Colors.NC}{Colors.BOLD}.{Colors.NC}")
    else:
        print_error("Validation failed! Please fix the issues above.")


def is_current_user_codeowner() -> bool:
    """
    Checks if current git user is listed in CODEOWNERS
    
    Returns:
        True if user is CODEOWNER, False otherwise
    """
    codeowners_path = Path('.github/CODEOWNERS')
    
    if not codeowners_path.exists():
        return False
    
    # Try to get GitHub username via gh CLI
    exit_code, gh_username, _ = run_command(
        ['gh', 'api', 'user', '--jq', '.login'],
        check=False
    )
    
    if exit_code != 0:
        # Fallback: try to get git user email
        _, git_email, _ = run_command(
            ['git', 'config', 'user.email'],
            check=False
        )
        git_email = git_email.strip()
        
        # Extract username from email (user@domain -> user)
        gh_username = git_email.split('@')[0] if git_email else ""
    else:
        gh_username = gh_username.strip()
    
    if not gh_username:
        return False
    
    # Read CODEOWNERS file
    try:
        with open(codeowners_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if username appears in CODEOWNERS (with @ prefix)
        # Also check username without @ for flexibility
        if f'@{gh_username}' in content or gh_username in content:
            return True
        
    except Exception as e:
        print_warning(f"Could not read CODEOWNERS file: {e}")
        return False
    
    return False


def main():
    """Main function"""
    # Enable ANSI colors on Windows 10+
    if sys.platform == 'win32':
        os.system('color')
    
    # Initialize validation results tracking
    results = ValidationResults()
    
    print_header("Dataform PR Validation (Local)")
    
    # Determine target branch
    target_branch = sys.argv[1] if len(sys.argv) > 1 else 'dev'
    current_branch = get_current_branch()
    
    print(f"Current branch: {Colors.BLUE}{current_branch}{Colors.NC}")
    print(f"Target branch:  {Colors.BLUE}{target_branch}{Colors.NC}")
    print()
    
    # Check if current user is CODEOWNER
    if is_current_user_codeowner():
        print_header("CODEOWNER Detected - Validation Skipped")
        print()
        print_success("You are listed in .github/CODEOWNERS")
        print()
        print(f"{Colors.BLUE}ℹ️  CODEOWNERS have implicit approval authority{Colors.NC}")
        print(f"{Colors.BLUE}ℹ️  All validation checks have been bypassed{Colors.NC}")
        print()
        print(f"{Colors.BOLD}Note:{Colors.NC} GitHub Actions will still verify your CODEOWNER status")
        print()
        print(f"{Colors.GREEN}Your branch is ready to merge into {Colors.BLUE}{target_branch}{Colors.NC}{Colors.GREEN}.{Colors.NC}")
        print()
        sys.exit(0)
    
    # Fetch target branch
    fetch_target_branch(target_branch)
    print()
    
    # =================================================================
    # CHECK 1: Branch freshness and merge conflicts
    # =================================================================
    commits_ahead, commits_behind, has_conflicts = check_branch_freshness(target_branch)
    
    if has_conflicts:
        results.add_check("CHECK 1: Branch freshness", "fail", "Merge conflicts detected")
    else:
        results.add_check("CHECK 1: Branch freshness", "pass")
    print()
    
    # =================================================================
    # CHECK 2: Verify changes are only in definitions/
    # =================================================================
    changed_files = get_changed_files(target_branch)
    
    if check_files_in_definitions(changed_files):
        results.add_check("CHECK 2: Files in definitions/", "pass")
    else:
        results.add_check("CHECK 2: Files in definitions/", "fail", "Files outside definitions/ detected")
    print()
    
    # =================================================================
    # CHECK 2b: Validate folder structure (3 levels with expected patterns)
    # =================================================================
    if validate_folder_structure(changed_files):
        results.add_check("CHECK 2b: Folder structure", "pass")
    else:
        results.add_check("CHECK 2b: Folder structure", "fail", "Invalid folder structure detected")
    print()
    
    # =================================================================
    # CHECK 3: Identify changed folders and required tags
    # =================================================================
    changed_folders = extract_changed_folders(changed_files)
    if check_required_tags(changed_folders):
        results.add_check("CHECK 3: Git Tag validation", "pass")
    else:
        results.add_check("CHECK 3: Git Tag validation", "fail", "Missing required Git tags")
    print()
    
    # =================================================================
    # CHECK 4: Validate semantic versioning using Git Tags
    # (reuse tags already fetched in CHECK 3)
    # =================================================================
    commit_tags = get_commit_tags('HEAD')
    
    if commit_tags:
        if check_version_conflicts_tags(commit_tags, target_branch):
            results.add_check("CHECK 4: Semantic versioning", "pass")
        else:
            results.add_check("CHECK 4: Semantic versioning", "fail", "Version conflicts detected")
        print()
    else:
        results.add_check("CHECK 4: Semantic versioning", "skip", "No Git tags on HEAD")
    
    # =================================================================
    # CHECK 5: Compile Dataform
    # =================================================================
    if compile_dataform():
        results.add_check("CHECK 5: Dataform compilation", "pass")
    else:
        results.add_check("CHECK 5: Dataform compilation", "fail", "Compilation failed")
    print()
    
    # =================================================================
    # CONSOLIDATED VALIDATION REPORT
    # =================================================================
    print_validation_report(results)
    
    # Final summary
    if results.has_failures():
        print_summary(False, target_branch, commits_ahead, commits_behind)
        sys.exit(1)
    else:
        print_summary(True, target_branch, commits_ahead, commits_behind)
        sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
        print_warning("Validation cancelled by user")
        sys.exit(130)
    except Exception as e:
        print()
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
