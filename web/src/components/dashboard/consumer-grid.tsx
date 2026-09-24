import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import type { ConsumerReadiness } from "@/lib/types";
import { CONSUMER_LABELS } from "@/lib/types";

interface ConsumerGridProps {
  consumers: ConsumerReadiness[];
}

export function ConsumerGrid({ consumers }: ConsumerGridProps) {
  if (consumers.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Downstream readiness</CardTitle>
        <p className="text-xs text-muted-foreground">
          Can each consumer act on this document without a follow-up meeting?
        </p>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {consumers.map((consumer) => (
            <div
              key={consumer.consumer}
              className="space-y-2 rounded-lg border p-3"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {CONSUMER_LABELS[consumer.consumer]}
                </span>
                <span className="text-sm font-semibold tabular-nums">
                  {Math.round(consumer.score * 100)}%
                </span>
              </div>
              <Progress value={consumer.score * 100} className="h-1.5" />
              {consumer.blocking.length > 0 ? (
                <Badge
                  variant="outline"
                  className="border-red-200 bg-red-50 text-[10px] text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
                >
                  {consumer.blocking.length} blocking gap
                  {consumer.blocking.length > 1 ? "s" : ""}
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
                >
                  No blocking gaps
                </Badge>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
