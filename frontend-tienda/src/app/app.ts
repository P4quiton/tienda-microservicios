import { Component } from '@angular/core';
import { Shell } from './layout/shell';
import { IntroLogo } from './shared/intro-logo';

@Component({
  selector: 'app-root',
  imports: [IntroLogo, Shell],
  template: '<app-intro-logo /><app-shell />',
})
export class App {}
