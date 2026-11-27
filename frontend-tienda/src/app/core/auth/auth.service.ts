import { Injectable, inject } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { StoreApiService } from '../api/store-api.service';
import { LoginRequest, LoginResponse, RegisterRequest, UserProfile } from '../models/api.models';
import { SessionService } from './session.service';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(StoreApiService);
  private readonly session = inject(SessionService);

  readonly user = this.session.user;
  readonly isAuthenticated = this.session.isAuthenticated;

  register(input: RegisterRequest): Observable<UserProfile> {
    return this.api.register(input);
  }

  login(input: LoginRequest): Observable<LoginResponse> {
    return this.api.login(input).pipe(
      tap(({ access_token, usuario, expires_in }) => this.session.start(access_token, usuario, expires_in)),
    );
  }

  logout(): void {
    this.session.end();
  }
}
