import os
import re
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent
APPS_DIR = BASE_DIR / "apps"

def count_lines(file_path):
    """Count lines in a file"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except:
        return 0

def count_classes(file_path, pattern):
    """Count classes matching a pattern in a file"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            return len(re.findall(pattern, content))
    except:
        return 0

def analyze_app(app_path):
    """Analyze a single app"""
    app_name = app_path.name
    
    # Count models
    models_file = app_path / "models.py"
    model_count = 0
    models_lines = 0
    if models_file.exists():
        models_lines = count_lines(models_file)
        model_count = count_classes(models_file, r'class\s+\w+\s*\(\s*models\.Model\s*\)')
    
    # Count views/viewsets
    views_file = app_path / "views.py"
    view_count = 0
    views_lines = 0
    if views_file.exists():
        views_lines = count_lines(views_file)
        view_count = count_classes(views_file, r'class\s+\w+\s*\(')
    
    # Count services
    services_dir = app_path / "services"
    service_count = 0
    services_lines = 0
    if services_dir.exists():
        for svc_file in services_dir.glob("*.py"):
            if svc_file.name != "__init__.py":
                services_lines += count_lines(svc_file)
                service_count += count_classes(svc_file, r'class\s+\w+Service')
    
    # Check migrations
    migrations_dir = app_path / "migrations"
    has_migrations = migrations_dir.exists() and len(list(migrations_dir.glob("*.py"))) > 1
    migration_count = len(list(migrations_dir.glob("*.py"))) - 1 if has_migrations else 0
    
    # Check tests
    tests_file = app_path / "tests.py"
    test_count = 0
    tests_lines = 0
    has_tests = tests_file.exists()
    if has_tests:
        tests_lines = count_lines(tests_file)
        test_count = count_classes(tests_file, r'def\s+test_')
        test_count += count_classes(tests_file, r'class\s+Test\w+')
    
    # Check for tests directory
    tests_dir = app_path / "tests"
    if tests_dir.exists():
        has_tests = True
        for test_file in tests_dir.glob("test_*.py"):
            tests_lines += count_lines(test_file)
            test_count += count_classes(test_file, r'def\s+test_')
            test_count += count_classes(test_file, r'class\s+Test\w+')
    
    return {
        'app': app_name,
        'models': model_count,
        'models_lines': models_lines,
        'views': view_count,
        'views_lines': views_lines,
        'services': service_count,
        'services_lines': services_lines,
        'migrations': migration_count,
        'has_migrations': has_migrations,
        'has_tests': has_tests,
        'test_count': test_count,
        'tests_lines': tests_lines,
    }

# List of apps from settings
apps_to_analyze = [
    'core', 'accounts', 'memberships', 'assessments', 'platform_sessions',
    'lifecycles', 'monitoring', 'tenants', 'authority', 'dashboard',
    'bookings', 'payments', 'attendance', 'sessions', 'communications',
    'analytics', 'actions', 'audit', 'verticals', 'catalog', 'enrollments',
    'activity', 'expenses', 'payouts', 'documents', 'reporting', 'renewals',
    'engagement', 'revenue', 'intake'
]

# Settings apps
settings_apps = ['roles', 'vocabulary', 'branding', 'whatsapp']

# Analyze apps in apps/
main_apps = []
for app_name in apps_to_analyze:
    app_path = APPS_DIR / app_name
    if app_path.exists():
        main_apps.append(analyze_app(app_path))

# Analyze settings sub-apps
for app_name in settings_apps:
    app_path = APPS_DIR / "settings" / app_name
    if app_path.exists():
        result = analyze_app(app_path)
        result['app'] = f"settings.{app_name}"
        main_apps.append(result)

# Analyze members, crm, platform_core (non-standard locations)
other_apps = []
for app_path in [BASE_DIR / "members", BASE_DIR / "crm", BASE_DIR / "platform_core"]:
    if app_path.exists():
        other_apps.append(analyze_app(app_path))

# Print to file instead
with open('audit_report.txt', 'w', encoding='utf-8') as f:
    f.write("=" * 100 + "\n")
    f.write("SAAS PLATFORM CODEBASE AUDIT\n")
    f.write("=" * 100 + "\n\n")

    f.write("MAIN APPS (apps/)\n")
    f.write("-" * 100 + "\n")
    f.write(f"{'App':<30} {'Models':<8} {'Views':<8} {'Services':<10} {'Tests':<8} {'Test #':<10} {'Migrations':<12}\n")
    f.write("-" * 100 + "\n")

    total_models = 0
    total_views = 0
    total_services = 0
    apps_without_tests = []

    for app in sorted(main_apps, key=lambda x: x['app']):
        has_test_marker = "Y" if app['has_tests'] else "N"
        f.write(f"{app['app']:<30} {app['models']:<8} {app['views']:<8} {app['services']:<10} {has_test_marker:<8} {app['test_count']:<10} {app['migrations']:<12}\n")
        
        total_models += app['models']
        total_views += app['views']
        total_services += app['services']
        
        if not app['has_tests']:
            apps_without_tests.append(app['app'])

    f.write("-" * 100 + "\n")
    f.write(f"{'TOTAL':<30} {total_models:<8} {total_views:<8} {total_services:<10}\n\n")

    f.write("OTHER APPS (non-standard locations)\n")
    f.write("-" * 100 + "\n")
    for app in other_apps:
        has_test_marker = "Y" if app['has_tests'] else "N"
        f.write(f"{app['app']:<30} {app['models']:<8} {app['views']:<8} {app['services']:<10} {has_test_marker:<8} {app['test_count']:<10} {app['migrations']:<12}\n")

    f.write("\n")
    f.write("=" * 100 + "\n")
    f.write("APPS WITHOUT TEST COVERAGE\n")
    f.write("=" * 100 + "\n")
    for app in sorted(apps_without_tests):
        f.write(f"  - {app}\n")

    f.write("\n")
    f.write("=" * 100 + "\n")
    f.write("SUMMARY STATISTICS\n")
    f.write("=" * 100 + "\n")
    f.write(f"Total apps analyzed: {len(main_apps) + len(other_apps)}\n")
    f.write(f"Total models: {total_models}\n")
    f.write(f"Total views: {total_views}\n")
    f.write(f"Total services: {total_services}\n")
    f.write(f"Apps without tests: {len(apps_without_tests)}\n")
    f.write(f"Apps with tests: {len(main_apps) + len(other_apps) - len(apps_without_tests)}\n")

print("Audit report written to audit_report.txt")
