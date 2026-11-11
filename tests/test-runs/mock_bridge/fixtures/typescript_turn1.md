Project: ts-priority-queue

File: package.json
```json
{
  "name": "ts-priority-queue",
  "version": "1.0.0",
  "description": "A modular TypeScript Priority Task Queue",
  "main": "dist/index.js",
  "scripts": {
    "build": "tsc",
    "start": "tsc && node dist/cli.js",
    "test": "tsc && node dist/queue.test.js"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "@types/node": "^20.0.0"
  }
}
```

File: tsconfig.json
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "rootDir": "./src",
    "outDir": "./dist",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src/**/*"]
}
```

File: src/types.ts
```typescript
export type Priority = "low" | "medium" | "high";

export interface TaskItem {
  id: string;
  title: string;
  priority: Priority;
  createdAt: number;
}
```

File: src/priorityQueue.ts
```typescript
import { TaskItem, Priority } from "./types";

export class PriorityQueue {
  private items: TaskItem[] = [];

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
    const newTask: TaskItem = {
      ...task,
      createdAt: Date.now(),
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

  public size(): number {
    return this.items.length;
  }
}
```

