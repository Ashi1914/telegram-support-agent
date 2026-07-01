import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

export const STATUS_LABEL = {
  open:        "Open",
  in_progress: "In Progress",
  resolved:    "Resolved",
  escalated:   "Escalated",
  closed:      "Closed",
  abandoned:   "Abandoned",
}

const STATUS_CLASS = {
  open:        "bg-blue-50 text-blue-700 border-blue-200",
  in_progress: "bg-amber-50 text-amber-700 border-amber-200",
  resolved:    "bg-green-50 text-green-700 border-green-200",
  escalated:   "bg-red-50 text-red-700 border-red-200",
  closed:      "bg-gray-100 text-gray-600 border-gray-200",
  abandoned:   "bg-yellow-50 text-yellow-700 border-yellow-200",
}

export function StatusBadge({ status, className }) {
  return (
    <Badge
      variant="outline"
      className={cn(STATUS_CLASS[status] ?? STATUS_CLASS.open, className)}
    >
      {STATUS_LABEL[status] ?? status}
    </Badge>
  )
}
