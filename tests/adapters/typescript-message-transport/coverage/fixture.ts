import { ClientKafka } from '@nestjs/microservices';

const TOPIC = process.env.TOPIC;

export class Worker {
  constructor(private readonly client: ClientKafka) {}

  go() {
    this.client.emit(TOPIC, {});
  }
}
