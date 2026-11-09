import { Badge } from "@/components/ui/badge";
import { eventStateLabel, eventStateTone } from "@/lib/domain/labels";

export function EventStateBadge({ state }: { state: string }) {
  return <Badge tone={eventStateTone(state)}>{eventStateLabel(state)}</Badge>;
}
