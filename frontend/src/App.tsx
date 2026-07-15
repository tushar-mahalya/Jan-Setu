import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { restoreSession } from "./api/client";
import { useAuth } from "./auth/AuthContext";
import Landing from "./pages/Landing";
import { LoadingState } from "./components/AppShell";
import AuthenticatedShell from "./components/AuthenticatedShell";

const About = lazy(() => import("./pages/About"));
const Login = lazy(() => import("./pages/Login"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const NewComplaint = lazy(() => import("./pages/NewComplaint"));
const ComplaintDetail = lazy(() => import("./pages/ComplaintDetail"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <AuthenticatedShell>{children}</AuthenticatedShell>;
}

export default function App() {
  const { login } = useAuth();
  const [isRestoring, setIsRestoring] = useState(true);

  useEffect(() => {
    let cancelled = false;
    restoreSession().then((token) => {
      if (cancelled) return;
      if (token) login(token);
      setIsRestoring(false);
    });
    return () => {
      cancelled = true;
    };
  }, [login]);

  if (isRestoring) return <LoadingState />;

  return (
    <Suspense fallback={<LoadingState />}>
      <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/about" element={<About />} />
      <Route path="/login" element={<Login />} />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/complaints/new"
        element={
          <RequireAuth>
            <NewComplaint />
          </RequireAuth>
        }
      />
      <Route
        path="/complaints/:id"
        element={
          <RequireAuth>
            <ComplaintDetail />
          </RequireAuth>
        }
      />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
