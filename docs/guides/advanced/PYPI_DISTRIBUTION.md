# PyPI Distribution Guide

This guide details the process of building and publishing the `eval_runner` package (MultiAgentEval) to PyPI.

## Prerequisites

1.  **PyPI Account**: You need an account on [PyPI](https://pypi.org/).
2.  **API Token**: Create an API token from your PyPI account settings for secure uploads.
3.  **Required Tools**: Install `build` and `twine`:
    ```bash
    pip install build twine
    ```

## Step 1: Prepare the Package

Ensure the `version` in `pyproject.toml` is correct for your new release.

```toml
[project]
name = "multiagent-verify"
version = "1.1.0" # Update this
...
```

Run the following command in the project root to ensure a clean build:

**Windows (PowerShell):**
```powershell
Remove-Item -Recurse -Force dist
```

**Windows (CMD):**
```cmd
rmdir /s /q dist
```

**Mac/Linux:**
```bash
rm -rf dist
```

Now, build the distributions:

```bash
python -m build
```

This will create a `dist/` directory containing two files:
- A source archive (`.tar.gz`)
- A built distribution (`.whl`)

## Step 3: Verify the Distributions

Use `twine` to check if your package description will render correctly on PyPI:

```bash
twine check dist/*
```

## Step 4: Upload to TestPyPI (Recommended)

Before publishing to the real PyPI, test the upload on TestPyPI:

```bash
twine upload --repository testpypi dist/*
```

You can then try installing it from TestPyPI:
```bash
# Use the new package name
pip install --index-url https://test.pypi.org/simple/ --no-deps multiagent-verify
```

## Step 5: Upload to PyPI

Once verified, publish to the official PyPI:

```bash
twine upload dist/*
```

Enter `__token__` as the username and your PyPI API token as the password.

---

## 🔐 Managing Credentials

You can avoid entering your token every time by using environment variables or a `.pypirc` file.

### Option A: Environment Variables (Recommended for CI)

Twine automatically looks for these variables:
```bash
# Windows (PowerShell)
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-your-token-here"

# Mac/Linux (Bash/Zsh)
export TWINE_USERNAME="__token__"
export TWINE_PASSWORD="pypi-your-token-here"
```

### Option B: The `.pypirc` File

Create a file at `%USERPROFILE%\.pypirc` (Windows) or `~/.pypirc` (Mac/Linux):

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-your-token-here

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-your-token-here
```

> [!CAUTION]
> Ensure your `.pypirc` file has restricted permissions (e.g., `chmod 600 ~/.pypirc` on Linux/Mac) to prevent other users from reading your tokens.

---

## Automation (Optional)

You can automate this process using GitHub Actions. See `.github/workflows/publish.yml` (if implemented) for an example.
