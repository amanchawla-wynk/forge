"use client";

import { useAppStore } from "@/lib/store";
import { SiteHeader } from "@/components/site-header";
import { SetupPanel } from "@/components/setup/setup-panel";
import { AssessmentDashboard } from "@/components/dashboard/assessment-dashboard";

export function AppShell() {
  const assessment = useAppStore((state) => state.assessment);

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-8 sm:px-6 lg:px-8">
        {assessment ? <AssessmentDashboard /> : <SetupPanel />}
      </main>
      <footer className="border-t bg-background/60 py-4 text-center text-xs text-muted-foreground">
        Forge is advisory, not an approval gate. This dashboard runs entirely
        on your machine; your API key is held in this browser tab only and is
        never written to disk by the local backend.
      </footer>
    </div>
  );
}
