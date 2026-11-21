import { FormEvent, useState } from "react";
import { User, api } from "../api";

export default function AuthPage({ onAuthenticated }: { onAuthenticated: (u: User) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user =
        mode === "login" ? await api.login(username, password) : await api.register(username, password);
      onAuthenticated(user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full flex items-center justify-center px-4">
      <form onSubmit={submit} className="bg-white border rounded-xl shadow-sm p-6 w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-brand-700">PDF Q&amp;A</h1>
          <p className="text-sm text-slate-500">Ask questions about your own documents.</p>
        </div>
        <label className="block text-sm">
          Username
          <input
            className="mt-1 w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label className="block text-sm">
          Password
          <input
            type="password"
            className="mt-1 w-full border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
          />
        </label>
        {error && (
          <div role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
            {error}
          </div>
        )}
        <button
          disabled={busy}
          className="w-full bg-brand-500 text-white py-2 rounded-md hover:bg-brand-700 disabled:opacity-60"
        >
          {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          className="w-full text-sm text-brand-700 hover:underline"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError("");
          }}
        >
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
