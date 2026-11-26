export class ApiError extends Error {
  constructor(status, message, field) {
    super(message);
    this.status = status;
    this.errors = field ? { [field]: [message] } : {};
  }
}
