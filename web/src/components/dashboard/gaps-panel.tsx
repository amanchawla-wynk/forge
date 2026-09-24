import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { CriterionResult } from "@/lib/types";
import { VERDICT_STYLES } from "@/lib/types";
import { cn } from "@/lib/utils";

interface GapsPanelProps {
  criteria: CriterionResult[];
}

export function GapsPanel({ criteria }: GapsPanelProps) {
  const sorted = [...criteria].sort((a, b) => {
    const order = { absent: 0, partial: 1, not_applicable: 2, present: 3 };
    return order[a.verdict] - order[b.verdict] || b.weight - a.weight;
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Criterion-by-criterion audit</CardTitle>
        <p className="text-xs text-muted-foreground">
          Every rubric criterion, its verdict, and any missing required
          fields. Absent and partial criteria drive the remediation loop.
        </p>
      </CardHeader>
      <CardContent>
        <Accordion type="single" collapsible className="w-full">
          {sorted.map((criterion) => {
            const style = VERDICT_STYLES[criterion.verdict];
            return (
              <AccordionItem key={criterion.criterion_id} value={criterion.criterion_id}>
                <AccordionTrigger className="hover:no-underline">
                  <div className="flex flex-1 items-center justify-between gap-3 pr-2">
                    <span className="text-left text-sm font-medium">
                      {criterion.name}
                    </span>
                    <div className="flex shrink-0 items-center gap-2">
                      {criterion.gate_triggered && (
                        <Badge
                          variant="outline"
                          className="border-red-200 bg-red-50 text-[10px] text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
                        >
                          Gate
                        </Badge>
                      )}
                      {criterion.agreement < 1 && (
                        <Badge variant="outline" className="text-[10px]">
                          {Math.round(criterion.agreement * 100)}% agreement
                        </Badge>
                      )}
                      <Badge className={cn("text-[10px]", style.className)}>
                        {style.label}
                      </Badge>
                    </div>
                  </div>
                </AccordionTrigger>
                <AccordionContent className="space-y-2 text-sm text-muted-foreground">
                  <p>{criterion.rationale}</p>
                  {criterion.missing.length > 0 && (
                    <p>
                      <span className="font-medium text-foreground">
                        Missing fields:
                      </span>{" "}
                      {criterion.missing.join(", ")}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-1 pt-1">
                    {criterion.consumers.map((consumer) => (
                      <Badge key={consumer} variant="outline" className="text-[10px]">
                        {consumer}
                      </Badge>
                    ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            );
          })}
        </Accordion>
      </CardContent>
    </Card>
  );
}
