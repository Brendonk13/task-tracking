import { useRef, useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import {
  TASK_STATE_LABEL,
  TASK_STATES,
  useCreateTask,
  useSetTaskState,
  useTask,
  type Task,
  type TaskHistoryEntry,
  type TaskState,
} from "@/api/hooks/tasks"
import type { TicketDetail } from "@/api/hooks/tickets"
import { ResumeSessionButton } from "@/components/sessions/ResumeSessionButton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { formatRelativeTime } from "@/lib/time"

const stateClassName: Record<TaskState, string> = {
  todo: "bg-muted text-muted-foreground",
  in_progress: "bg-sky-500/15 text-sky-700 border-sky-500/30 dark:text-sky-300",
  done: "bg-emerald-500/15 text-emerald-700 border-emerald-500/30 dark:text-emerald-300",
  cancelled: "bg-muted text-muted-foreground line-through",
}

function TaskStateChip({ state }: { state: TaskState }) {
  return (
    <Badge variant="outline" className={cn(stateClassName[state])}>
      {TASK_STATE_LABEL[state]}
    </Badge>
  )
}

function HistoryItem({ entry }: { entry: TaskHistoryEntry }) {
  return (
    <li data-kind={entry.kind} className="flex flex-col gap-0.5">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span data-slot="history-actor" className="font-medium text-foreground">
          {entry.actor.name}
        </span>
        <time dateTime={entry.created_at} title={new Date(entry.created_at).toLocaleString()}>
          {formatRelativeTime(entry.created_at)}
        </time>
        {entry.actor.directory !== null && (
          <ResumeSessionButton
            sessionId={entry.actor.session_id}
            directory={entry.actor.directory}
            name={entry.actor.name}
          />
        )}
      </div>
      <p className="text-sm text-muted-foreground">{entry.body}</p>
      {entry.reason !== null && (
        <p className="text-sm">
          <span className="text-muted-foreground">Reason: </span>
          <span className="italic">{entry.reason}</span>
        </p>
      )}
    </li>
  )
}

function TaskHistory({ task }: { task: Task }) {
  const { data, isPending, isError } = useTask(task.id)
  if (isPending) return <p className="text-sm text-muted-foreground">Loading history…</p>
  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load task history.
      </p>
    )
  }
  if (data.history.length === 0) {
    return <p className="text-sm text-muted-foreground">No changes yet.</p>
  }
  return (
    <ol aria-label={`History of ${task.title}`} className="flex flex-col gap-2 border-l pl-3">
      {data.history.map((entry) => (
        <HistoryItem key={entry.id} entry={entry} />
      ))}
    </ol>
  )
}

function TaskRow({ task, byId, ticketId }: { task: Task; byId: Map<number, Task>; ticketId: number }) {
  const [expanded, setExpanded] = useState(false)
  const setState = useSetTaskState(task.id, ticketId)
  const blocked = task.blocked_by.length > 0
  const titleOf = (id: number) => byId.get(id)?.title ?? `#${id}`
  const Chevron = expanded ? ChevronDown : ChevronRight

  return (
    <li data-state={task.state} data-blocked={blocked} className="flex flex-col gap-1 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="inline-flex items-center gap-1 text-sm font-medium underline-offset-4 hover:underline"
        >
          <Chevron aria-hidden="true" className="size-4 text-muted-foreground" />
          {task.title}
        </button>
        <TaskStateChip state={task.state} />
        {blocked && (
          <Badge variant="destructive" title={`Blocked by ${task.blocked_by.map(titleOf).join(", ")}`}>
            blocked
          </Badge>
        )}
        <select
          aria-label={`State of ${task.title}`}
          value={task.state}
          disabled={setState.isPending}
          onChange={(event) => setState.mutate(event.target.value as TaskState)}
          className="ml-auto h-7 rounded-md border border-input bg-background px-2 text-xs shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {TASK_STATES.map((state) => (
            <option key={state} value={state}>
              {TASK_STATE_LABEL[state]}
            </option>
          ))}
        </select>
      </div>
      {task.depends_on.length > 0 && (
        <p className="pl-5 text-xs text-muted-foreground">
          Depends on:{" "}
          {task.depends_on.map((id, index) => (
            <span key={id}>
              {index > 0 && ", "}
              <span className={cn(task.blocked_by.includes(id) && "font-medium text-foreground")}>
                {titleOf(id)}
              </span>
            </span>
          ))}
        </p>
      )}
      {task.description !== "" && (
        <p className="pl-5 text-sm text-foreground/90 whitespace-pre-wrap">{task.description}</p>
      )}
      {setState.isError && (
        <p role="alert" className="pl-5 text-sm text-destructive">
          Could not change task state.
        </p>
      )}
      {expanded && (
        <div className="pl-5 pt-1">
          <TaskHistory task={task} />
        </div>
      )}
    </li>
  )
}

function AddTaskForm({ ticketId, tasks }: { ticketId: number; tasks: Task[] }) {
  const [title, setTitle] = useState("")
  const [dependsOn, setDependsOn] = useState<number[]>([])
  const titleRef = useRef<HTMLInputElement>(null)
  const createTask = useCreateTask(ticketId)
  const canSubmit = title.trim() !== "" && !createTask.isPending

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        if (!canSubmit) return
        createTask.mutate(
          { title: title.trim(), depends_on: dependsOn },
          {
            onSuccess: () => {
              setTitle("")
              setDependsOn([])
              titleRef.current?.focus()
            },
          },
        )
      }}
    >
      <div className="flex min-w-56 flex-1 flex-col gap-1">
        <Label htmlFor="task-title">New task</Label>
        <Input
          ref={titleRef}
          id="task-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Write the migration"
          className="h-8"
        />
      </div>
      {tasks.length > 0 && (
        <div className="flex flex-col gap-1">
          <Label htmlFor="task-depends-on">Depends on</Label>
          <select
            id="task-depends-on"
            multiple
            value={dependsOn.map(String)}
            onChange={(event) =>
              setDependsOn(Array.from(event.target.selectedOptions, (option) => Number(option.value)))
            }
            className="min-w-40 rounded-md border border-input bg-background px-2 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            size={Math.min(tasks.length, 4)}
          >
            {tasks.map((task) => (
              <option key={task.id} value={task.id}>
                {task.title}
              </option>
            ))}
          </select>
        </div>
      )}
      <Button type="submit" size="sm" disabled={!canSubmit}>
        Add task
      </Button>
      {createTask.isError && (
        <p role="alert" className="basis-full text-sm text-destructive">
          Could not add task.
        </p>
      )}
    </form>
  )
}

export function TaskList({ ticket }: { ticket: TicketDetail }) {
  const byId = new Map(ticket.tasks.map((task) => [task.id, task]))
  return (
    <section aria-labelledby="tasks-heading" className="flex flex-col gap-2">
      <h2 id="tasks-heading" className="text-lg font-medium">
        Tasks
      </h2>
      {ticket.tasks.length === 0 ? (
        <p className="text-sm text-muted-foreground">No tasks yet.</p>
      ) : (
        <ul aria-label="Tasks" className="flex flex-col divide-y">
          {ticket.tasks.map((task) => (
            <TaskRow key={task.id} task={task} byId={byId} ticketId={ticket.id} />
          ))}
        </ul>
      )}
      <AddTaskForm ticketId={ticket.id} tasks={ticket.tasks} />
    </section>
  )
}
