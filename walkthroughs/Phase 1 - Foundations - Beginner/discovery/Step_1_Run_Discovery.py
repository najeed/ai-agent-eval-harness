import shlex
import subprocess
import sys


def run_cmd(cmd):
    """Executes a CLI command and returns the output string (Secured v1.6.0)."""
    try:
        # Securely resolve python-m commands using the current interpreter
        args = shlex.split(cmd)
        if args[0] == "python":
            args[0] = sys.executable

        result = subprocess.run(args, capture_output=True, text=True, shell=False, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"


def main():
    print("============================================")
    print("Welcome, Evaluation Engineer!")
    print("Scenario: The Map of the Industrial Maze")
    print("============================================")
    print("\nIn Aethelgard Industrial, we don't 'search' for files.")
    print("We ask the Scenario Catalog. Let's see our entire map.")

    input("\n[Press ENTER] to list all indexed scenarios...")

    # Run the list command
    print("\n   [CLI] Running: agentv list")
    output = run_cmd("python -m eval_runner.cli list")
    print("-" * 40)
    print(output)
    print("-" * 40)

    print("\nImpressive, isn't it? But we need to be more precise.")
    print("The CTO wants to see our 'Finance' capabilities specifically.")

    input("\n[Press ENTER] to filter the catalog for 'finance'...")

    # Run the search command
    print("\n   [CLI] Running: agentv list --search finance")
    search_output = run_cmd("python -m eval_runner.cli list --search finance")
    print("-" * 40)
    print(search_output)
    print("-" * 40)

    print("\n🎉 Success!")
    print("You've successfully mapped the first sector of the industrial maze.")
    print("\nNext, we'll teach you how to 'talk' to these agents.")
    print("Proceed to: 02_Native_Adapters (The Multilingual Agent)")
    print("============================================")


if __name__ == "__main__":
    main()
