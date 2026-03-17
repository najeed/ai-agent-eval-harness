
import sys
import traceback

try:
    from eval_runner import cli
    print("CLI imported successfully")
except Exception:
    print("CLI import failed")
    traceback.print_exc()
    sys.exit(1)

try:
    # Attempt to initialize or run a small part of main
    import argparse
    parser = argparse.ArgumentParser()
    # Mocking the subparsers structure to see if registration fails
    subparsers = parser.add_subparsers(dest="command")
    
    # Check if a specific plugin registration is failing
    from eval_runner import plugins
    print(f"Plugins registered: {len(plugins.manager._plugins)}")
    for name, plugin in plugins.manager._plugins.items():
        print(f" - {name}: {type(plugin).__name__}")
        
except Exception:
    traceback.print_exc()
    sys.exit(1)
