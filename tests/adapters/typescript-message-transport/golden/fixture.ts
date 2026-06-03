import { EventPattern, MessagePattern, ClientKafka } from '@nestjs/microservices';

export class OrderController {
  constructor(private readonly client: ClientKafka) {}

  @MessagePattern('order_create')
  create(data: any) {}

  publish() {
    this.client.emit('inventory_new_order', {});
  }
}
