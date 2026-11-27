import { Injectable, computed, signal } from '@angular/core';
import { UserProfile } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly accessTokenState = signal<string | null>(null);
  private readonly userState = signal<UserProfile | null>(null);
  private readonly expiresAtState = signal<number | null>(null);
  private readonly expiredState = signal(false);
  private expiryTimer?: ReturnType<typeof setTimeout>;

  readonly user = this.userState.asReadonly();
  readonly expired = this.expiredState.asReadonly();
  readonly isAuthenticated = computed(() => {
    const expiresAt = this.expiresAtState();
    return this.accessTokenState() !== null && (expiresAt === null || Date.now() < expiresAt);
  });

  get accessToken(): string | null {
    if (!this.isAuthenticated()) {
      this.end();
      return null;
    }
    return this.accessTokenState();
  }

  start(accessToken: string, user: UserProfile, expiresInSeconds?: number): void {
    if (this.expiryTimer) clearTimeout(this.expiryTimer);
    this.accessTokenState.set(accessToken);
    this.userState.set(user);
    this.expiredState.set(false);
    this.expiresAtState.set(expiresInSeconds ? Date.now() + expiresInSeconds * 1000 : null);
    if (expiresInSeconds) this.expiryTimer = setTimeout(() => this.expire(), expiresInSeconds * 1000);
  }

  end(): void {
    if (this.expiryTimer) clearTimeout(this.expiryTimer);
    this.expiryTimer = undefined;
    this.accessTokenState.set(null);
    this.userState.set(null);
    this.expiresAtState.set(null);
    this.expiredState.set(false);
  }

  expire(): void {
    this.end();
    this.expiredState.set(true);
  }
}
