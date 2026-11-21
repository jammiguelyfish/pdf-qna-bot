import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { ApiError, User, api } from "./api";
import AuthPage from "./pages/AuthPage";
import ChatPage from "./pages/ChatPage";
import DocumentsPage from "./pages/DocumentsPage";

const tab = "px-3 py-2 rounded-md text-sm font-medium hover:bg-brand-50 hover:text-brand-700";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch((e) => {
        if (!(e instanceof ApiError) || e.status !== 401) console.error(e);
      })
      .finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!user) return <AuthPage onAuthenticated={setUser} />;

  return (
    <div className="h-full flex flex-col">
      <header className="bg-white border-b">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-6">
          <span className="text-lg font-semibold text-brand-700">PDF Q&amp;A</span>
          <nav className="flex gap-1">
            <NavLink to="/documents" className={({ isActive }) => `${tab} ${isActive ? "bg-brand-50 text-brand-700" : ""}`}>
              Documents
            </NavLink>
            <NavLink to="/chat" className={({ isActive }) => `${tab} ${isActive ? "bg-brand-50 text-brand-700" : ""}`}>
              Chat
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-600">
            <span>{user.username}</span>
            <button
              className="border rounded px-2 py-1 hover:bg-slate-50"
              onClick={() => api.logout().finally(() => setUser(null))}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1 min-h-0 max-w-6xl mx-auto w-full px-4 py-6">
        <Routes>
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="*" element={<Navigate to="/documents" replace />} />
        </Routes>
      </main>
    </div>
  );
}
