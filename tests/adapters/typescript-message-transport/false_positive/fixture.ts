import { EventEmitter } from 'events';

export class Worker {
  constructor(private readonly bus: EventEmitter) {}

  go() {
    this.bus.emit('not_an_event', {});
  }
}
