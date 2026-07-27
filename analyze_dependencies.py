import os
import re
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent
APPS_DIR = BASE_DIR / "apps"

def find_imports(file_path):
    """Extract imports from a Python file"""
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            # Find from ... import ... patterns
            from_imports = re.findall(r'from\s+(?:\.+)?(\w+|[\w.]+)\s+import', content)
            # Find import ... patterns
            direct_imports = re.findall(r'import\s+(?:\.+)?(\w+|[\w.]+)', content)
            imports.update(from_imports)
            imports.update(direct_imports)
    except:
        pass
    return imports

def analyze_app_dependencies(app_path):
    """Analyze dependencies for an app"""
    deps = set()
    
    # Check models.py
    models_file = app_path / "models.py"
    if models_file.exists():
        deps.update(find_imports(models_file))
    
    # Check views.py
    views_file = app_path / "views.py"
    if views_file.exists():
        deps.update(find_imports(views_file))
    
    # Check services
    services_dir = app_path / "services"
    if services_dir.exists():
        for svc_file in services_dir.glob("*.py"):
            if svc_file.name != "__init__.py":
                deps.update(find_imports(svc_file))
    
    return deps

# List of main apps
apps_to_analyze = [
    'core', 'accounts', 'memberships', 'assessments', 'platform_sessions',
    'lifecycles', 'monitoring', 'tenants', 'authority', 'dashboard',
    'bookings', 'payments', 'attendance', 'sessions', 'communications',
    'analytics', 'actions', 'audit', 'verticals', 'catalog', 'enrollments',
    'activity', 'expenses', 'payouts', 'documents', 'reporting', 'renewals',
    'engagement', 'revenue', 'intake'
]

settings_apps = ['roles', 'vocabulary', 'branding', 'whatsapp']

# Map of app names to their paths
app_map = {}
for app_name in apps_to_analyze:
    app_map[app_name] = APPS_DIR / app_name

for app_name in settings_apps:
    app_map[f"settings_{app_name}"] = APPS_DIR / "settings" / app_name

for app_path in [BASE_DIR / "members", BASE_DIR / "crm", BASE_DIR / "platform_core"]:
    if app_path.exists():
        app_map[app_path.name] = app_path

# Analyze dependencies
dependencies = {}
for app_name, app_path in app_map.items():
    if app_path.exists():
        deps = analyze_app_dependencies(app_path)
        # Filter to only our apps
        our_apps = set(app_map.keys()) | set(apps_to_analyze)
        relevant_deps = deps & our_apps
        if relevant_deps:
            dependencies[app_name] = relevant_deps

# Check conftest and fixtures
conftest_path = BASE_DIR / "conftest.py"
has_conftest = conftest_path.exists()

# Check pytest.ini
pytest_ini_path = BASE_DIR / "pytest.ini"
has_pytest_ini = pytest_ini_path.exists()

# Write analysis
with open('dependency_analysis.txt', 'w', encoding='utf-8') as f:
    f.write("=" * 100 + "\n")
    f.write("DEPENDENCY ANALYSIS\n")
    f.write("=" * 100 + "\n\n")
    
    f.write("APP DEPENDENCIES\n")
    f.write("-" * 100 + "\n")
    for app_name in sorted(dependencies.keys()):
        deps = dependencies[app_name]
        f.write(f"{app_name}: {', '.join(sorted(deps))}\n")
    
    if not dependencies:
        f.write("No direct inter-app dependencies detected via imports.\n")
    
    f.write("\n")
    f.write("=" * 100 + "\n")
    f.write("TEST INFRASTRUCTURE\n")
    f.write("=" * 100 + "\n")
    f.write(f"conftest.py exists: {has_conftest}\n")
    f.write(f"pytest.ini exists: {has_pytest_ini}\n")
    
    if has_conftest:
        f.write(f"\nconftest.py location: {conftest_path}\n")
        conftest_content = open(conftest_path, 'r', encoding='utf-8', errors='ignore').read()
        fixtures = re.findall(r'@pytest\.fixture.*?\ndef\s+(\w+)', conftest_content, re.DOTALL)
        f.write(f"Fixtures defined: {', '.join(fixtures) if fixtures else 'None'}\n")

print("Dependency analysis written to dependency_analysis.txt")
