# Frontend Contribution Guidelines

NextRound's frontend is built using Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui, and TanStack Query.

---

## 1. Directory Modularity

We separate reusable layout pieces from features specific to application modules:

* **`src/components/ui/`**: Base UI elements (e.g. Button, Dialog, Tooltip) initialized via `shadcn/ui`. *Do not write direct business logic inside these files.*
* **`src/components/`**: Multi-page components (e.g. Layout, Navbar, Sidebar).
* **`src/features/`**: Feature modules containing specific views, components, and hooks.
  - Structure:
    ```
    src/features/auth/
    ├── components/    # Login/Register forms
    ├── hooks/         # useAuth mutations
    ├── services/      # authApi fetchers
    └── index.ts       # Public exports
    ```
* **`src/app/`**: Next.js App Router folders specifying URLs and page layouts. Keep these pages thin by delegating views to `features/`.

---

## 2. API Integration Strategy

We handle backend communication using **Axios** and **TanStack Query** (React Query):

1. **API Client**: Always use the axios instance from `src/lib/api.ts` (configured with the base URL and JWT token headers).
2. **Fetchers**: Declare endpoints in `services/`:
   ```typescript
   import api from "@/lib/api";
   import { User } from "@/types";

   export const fetchUserProfile = async (): Promise<User> => {
     const { data } = await api.get("/users/me");
     return data;
   };
   ```
3. **Query Hooks**: Wrap fetchers in TanStack Query hooks:
   ```typescript
   import { useQuery } from "@tanstack/react-query";
   import { fetchUserProfile } from "../services/profile";

   export const useProfile = () => {
     return useQuery({
       queryKey: ["profile"],
       queryFn: fetchUserProfile,
     });
   };
   ```

---

## 3. Form Validation Rules

Implement forms using **React Hook Form** integrated with **Zod** schema validations:

```typescript
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";

const formSchema = z.object({
  email: z.string().email("Invalid email address"),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

export const LoginForm = () => {
  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = (values: z.infer<typeof formSchema>) => {
    // Process submission
  };
};
```

---

## 4. Styling & Theming Policies

1. **Aesthetics first**: Use Tailwind CSS for responsive formatting.
2. **Variables usage**: Rely on CSS variables defined in [src/app/globals.css](file:///D:/NextRound/frontend/src/app/globals.css) for backgrounds, focus borders, and states.
3. **Hover states**: Apply micro-animations (e.g. `transition-all duration-200 hover:scale-[1.02] hover:shadow-lg`) on buttons, anchor links, and cards.
4. **Layout scaling**: Use `sm:`, `md:`, `lg:`, `xl:` breakpoints to guarantee responsiveness from small mobile interfaces up to desktop monitors.
