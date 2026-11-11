Project: ts-priority-queue

File: src/priorityQueue.ts
```typescript
import { TaskItem, Priority } from "./types";

export class PriorityQueue {
  private items: TaskItem[] = [];
  private seq = 0;

  private getPriorityWeight(priority: Priority): number {
    switch (priority) {
      case "high":
        return 3;
      case "medium":
        return 2;
      case "low":
        return 1;
      default:
        return 0;
    }
  }

  public enqueue(task: Omit<TaskItem, "createdAt">): TaskItem {
    if (!task.title || task.title.trim() === "") {
      throw new Error("Task title cannot be empty");
    }
    const newTask: TaskItem = {
      ...task,
      createdAt: ++this.seq,
    };
    this.items.push(newTask);
    return newTask;
  }

  public dequeue(): TaskItem | undefined {
    if (this.items.length === 0) {
      return undefined;
    }
    let highestIndex = 0;
    let highestWeight = this.getPriorityWeight(this.items[0].priority);
    for (let i = 1; i < this.items.length; i++) {
      const currentWeight = this.getPriorityWeight(this.items[i].priority);
      if (currentWeight > highestWeight) {
        highestWeight = currentWeight;
        highestIndex = i;
      } else if (currentWeight === highestWeight && this.items[i].createdAt < this.items[highestIndex].createdAt) {
        highestIndex = i;
      }
    }
    const [dequeuedItem] = this.items.splice(highestIndex, 1);
    return dequeuedItem;
  }

  public peek(): TaskItem | undefined {
    if (this.items.length === 0) {
      return undefined;
    }
    let highestIndex = 0;
    let highestWeight = this.getPriorityWeight(this.items[0].priority);
    for (let i = 1; i < this.items.length; i++) {
      const currentWeight = this.getPriorityWeight(this.items[i].priority);
      if (currentWeight > highestWeight) {
        highestWeight = currentWeight;
        highestIndex = i;
      }
    }
    return this.items[highestIndex];
  }

  public filterByPriority(priority: Priority): TaskItem[] {
    return this.items.filter((item) => item.priority === priority);
  }

  public size(): number {
    return this.items.length;
  }
}
```

File: src/cli.ts
```typescript
import { PriorityQueue } from "./priorityQueue";

const pq = new PriorityQueue();
pq.enqueue({ id: "1", title: "Update docs", priority: "low" });
pq.enqueue({ id: "2", title: "Fix critical bug", priority: "high" });
pq.enqueue({ id: "3", title: "Refactor module", priority: "medium" });

console.log("Queue size:", pq.size());
while (pq.size() > 0) {
  const item = pq.dequeue();
  if (item) {
    console.log(`[${item.priority.toUpperCase()}] ${item.title}`);
  }
}
```

File: src/queue.test.ts
```typescript
import assert from "node:assert/strict";
import { PriorityQueue } from "./priorityQueue";

const pq = new PriorityQueue();
pq.enqueue({ id: "1", title: "Low task", priority: "low" });
pq.enqueue({ id: "2", title: "High task", priority: "high" });
pq.enqueue({ id: "3", title: "Medium task", priority: "medium" });

assert.strictEqual(pq.filterByPriority("high").length, 1);
assert.strictEqual(pq.dequeue()?.priority, "high");
assert.strictEqual(pq.dequeue()?.priority, "medium");
assert.strictEqual(pq.dequeue()?.priority, "low");

assert.throws(() => {
  pq.enqueue({ id: "4", title: "   ", priority: "high" });
}, /Task title cannot be empty/);

console.log("ALL TESTS PASSED");
```

