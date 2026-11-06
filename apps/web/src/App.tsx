import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "@/features/auth/AuthContext";
import { Layout } from "@/components/Layout";
import { LoginPage } from "@/routes/LoginPage";
import { DashboardPage } from "@/routes/DashboardPage";
import { CalendarPage } from "@/routes/CalendarPage";
import { CatalogPage } from "@/routes/CatalogPage";
import { CatalogDetailPage } from "@/routes/CatalogDetailPage";
import { EventDetailPage } from "@/routes/EventDetailPage";
import { EventCreatePage } from "@/routes/EventCreatePage";
import { SubscriptionsPage } from "@/routes/SubscriptionsPage";
import { BannerDemoPage } from "@/routes/BannerDemoPage";
import { AboutPage } from "@/routes/AboutPage";
import { AdminShell } from "@/routes/admin/AdminShell";
import { AdminOverviewPage } from "@/routes/admin/AdminOverviewPage";
import { AdminCatalogPage } from "@/routes/admin/AdminCatalogPage";
import { AdminServiceNowPage } from "@/routes/admin/AdminServiceNowPage";
import { AdminNotificationsPage } from "@/routes/admin/AdminNotificationsPage";
import { AdminUsersPage } from "@/routes/admin/AdminUsersPage";
import { AdminJobsPage } from "@/routes/admin/AdminJobsPage";
import { AdminAuditPage } from "@/routes/admin/AdminAuditPage";
import type { ReactNode } from "react";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-ink-500">
        Loading session…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="calendar" element={<CalendarPage />} />
          <Route path="catalog" element={<CatalogPage />} />
          <Route path="catalog/:id" element={<CatalogDetailPage />} />
          <Route path="subscriptions" element={<SubscriptionsPage />} />
          <Route path="banner-demo" element={<BannerDemoPage />} />
          <Route path="about" element={<AboutPage />} />
          <Route path="events/new" element={<EventCreatePage />} />
          <Route path="events/:id" element={<EventDetailPage />} />
          <Route path="admin" element={<AdminShell />}>
            <Route index element={<AdminOverviewPage />} />
            <Route path="catalog" element={<AdminCatalogPage />} />
            <Route path="servicenow" element={<AdminServiceNowPage />} />
            <Route path="notifications" element={<AdminNotificationsPage />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="jobs" element={<AdminJobsPage />} />
            <Route path="audit" element={<AdminAuditPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
