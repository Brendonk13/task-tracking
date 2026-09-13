import { Filter } from "lucide-react"
import { useStatuses } from "@/api/hooks/statuses"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

interface StatusFilterProps {
  selected: string[]
  onChange: (selected: string[]) => void
}

export function StatusFilter({ selected, onChange }: StatusFilterProps) {
  const { data: statuses } = useStatuses()

  const toggle = (name: string, checked: boolean) => {
    if (checked) {
      if (!selected.includes(name)) onChange([...selected, name])
    } else {
      onChange(selected.filter((s) => s !== name))
    }
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" aria-label="Filter by status">
          <Filter aria-hidden="true" />
          Status
          {selected.length > 0 && (
            <span className="ml-1 rounded-full bg-primary px-1.5 text-xs text-primary-foreground tabular-nums">
              {selected.length}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-2">
        <fieldset className="flex flex-col gap-1">
          <legend className="px-2 pb-1 text-xs font-medium text-muted-foreground">
            Filter by status
          </legend>
          {statuses?.map((status) => {
            const id = `status-filter-${status.name}`
            return (
              <div
                key={status.name}
                className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-muted"
              >
                <Checkbox
                  id={id}
                  checked={selected.includes(status.name)}
                  onCheckedChange={(checked) => toggle(status.name, checked === true)}
                />
                <label htmlFor={id} className="flex-1 cursor-pointer text-sm select-none">
                  {status.name}
                </label>
              </div>
            )
          })}
        </fieldset>
      </PopoverContent>
    </Popover>
  )
}
