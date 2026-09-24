import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { AssessmentResponse } from "@/lib/types";
import { BAND_STYLES } from "@/lib/types";
import { cn } from "@/lib/utils";

interface BandSummaryCardProps {
  response: AssessmentResponse;
}

export function BandSummaryCard({ response }: BandSummaryCardProps) {
  const { assessment, report } = response;
  const band = BAND_STYLES[assessment.band] ?? BAND_STYLES.not_a_prd;
  const uncapped = BAND_STYLES[assessment.uncapped_band];

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle className="text-xl">{report.headline}</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">{report.summary}</p>
        </div>
        <Badge className={cn("shrink-0 border text-sm", band.className)} variant="outline">
          {band.label}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {assessment.band !== assessment.uncapped_band && uncapped && (
          <p className="text-xs text-muted-foreground">
            A failed gate capped this result at <strong>{band.label}</strong>;
            weighted score alone would have reached{" "}
            <strong>{uncapped.label}</strong>.
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-3">
          <Metric
            label="Weighted score"
            value={`${Math.round(assessment.raw_score * 100)}%`}
            progress={assessment.raw_score * 100}
          />
          <Metric
            label="Extraction confidence"
            value={`${Math.round(assessment.confidence * 100)}%`}
            progress={assessment.confidence * 100}
            hint={`${response.run_count} of ${response.expected_run_count} expected runs`}
          />
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Rubric</p>
            <p className="text-sm font-medium">
              {assessment.rubric_id}@{assessment.rubric_version}
            </p>
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
              {assessment.calibration_status.replace("_", " ")}
            </Badge>
          </div>
        </div>

        {assessment.gates_failed.length > 0 && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            Failed gate{assessment.gates_failed.length > 1 ? "s" : ""} capping
            readiness: {assessment.gates_failed.join(", ")}
          </div>
        )}

        <p className="text-xs text-muted-foreground">{report.confidence_note}</p>
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  value,
  progress,
  hint,
}: {
  label: string;
  value: string;
  progress: number;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
      <Progress value={progress} className="h-1.5" />
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
