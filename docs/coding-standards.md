# Coding Standards & Quality Policies

To maintain code readability and minimize regressions, all contributors must follow these coding standards.

---

## 1. Python (Backend) Rules

* **Formatting**: Standardize Python files via `black` (88 character line limit).
* **Linting & Import Sorting**: Code linting and import sorting are handled by `ruff` (with rules `E`, `F`, `I`, `N`, `UP`, `B`, `C4`). Standalone `isort` is no longer used; Ruff is responsible for import sorting via the `I` rules.
* **Type Safety**: Apply type annotations to function parameters and return structures. All types are checked using `mypy --strict`.
* **Docstring standard**: Apply Google-style docstrings to public services, helper endpoints, and repositories:
  ```python
  def verify_password(plain_password: str, hashed_password: str) -> bool:
      """
      Verify a plain password against its hashed representation.

      Args:
          plain_password: The unhashed raw input string.
          hashed_password: The target hashed string.

      Returns:
          True if password matches, False otherwise.
      """
  ```

---

## 2. TypeScript / React (Frontend) Rules

* **Formatting**: Format layout pages using `prettier` configured with `.prettierrc` rules.
* **No Implicit Any**: Avoid using `any` types. If dynamic objects are needed, declare them as `unknown` or utilize union types.
* **Component Structures**: Declare React functional components using standard arrow syntax with explicit return types:
  ```typescript
  interface CardProps {
    title: string;
  }

  export const Card: React.FC<CardProps> = ({ title }) => {
    return <div className="p-4">{title}</div>;
  };
  ```
* **Hook Dependency Lists**: Always include dependencies inside `useEffect` or `useMemo` hooks. Avoid empty lists if they use local scope values.

---

## 3. Version Control & Git Guidelines

We use semantic commit messages to format repository history:

```
<type>(<scope>): <subject>

[optional body]
```

### Commit Types:
* **`feat`**: Introduces a new feature or endpoint.
* **`fix`**: Standard bug fix.
* **`docs`**: Changes to README, docs, or comments.
* **`style`**: Changes that do not affect code logic (formatting, layout white-spaces).
* **`refactor`**: Rewriting code without introducing features or fixing bugs.
* **`test`**: Adding or modifying test suites.
* **`chore`**: Maintenance (dependencies upgrades, webpack configuration modifications).

---

## 4. Local Verification
Run formatting and lint checks locally before opening a pull request:
* **Makefile Workflow (Recommended)**:
  ```bash
  make format   # Formats code with black and ruff --fix
  make check    # Runs black --check, ruff check, mypy, and pytest
  make test     # Runs pytest suite
  ```
* **NPM Script**:
  ```bash
  npm run check
  ```
* **Python Helper Script**:
  ```bash
  python scripts/check_all.py
  ```
All checks must pass with zero errors before pull requests will be approved.
