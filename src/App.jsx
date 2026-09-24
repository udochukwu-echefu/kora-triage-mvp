import { lazy, Suspense } from "react";

// Visitors to "/" only download the landing page; the workspace loads on /app.
const LandingPage = lazy(() => import("./components/LandingPage"));
const Workspace = lazy(() => import("./workspace/Workspace"));

export default function App() {
  const onLanding = window.location.pathname === "/" && !new URLSearchParams(window.location.search).has("case");
  return (
    <Suspense fallback={<div className="min-h-screen bg-canvas" aria-busy="true" />}>
      {onLanding ? <LandingPage /> : <Workspace />}
    </Suspense>
  );
}
