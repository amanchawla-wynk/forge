import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

interface WarningsBannerProps {
  warnings: string[];
}

export function WarningsBanner({ warnings }: WarningsBannerProps) {
  if (warnings.length === 0) return null;

  return (
    <Alert className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40">
      <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
      <AlertTitle className="text-amber-900 dark:text-amber-300">
        Read before acting on this result
      </AlertTitle>
      <AlertDescription>
        <ul className="mt-1 list-disc space-y-1 pl-4 text-amber-900/90 dark:text-amber-300/90">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
