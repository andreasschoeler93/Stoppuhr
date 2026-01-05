import {Routes} from '@angular/router';
import {StoppuhrComponent} from './tabs/stoppuhr/stoppuhr.component';
import {EinstellungenComponent} from './tabs/einstellungen/einstellungen.component';
import {SystemstatusComponent} from './tabs/systemstatus/systemstatus.component';
import {NetzwerkComponent} from './tabs/netzwerk/netzwerk.component';

export const routes: Routes = [
  {path: '', pathMatch: 'full', redirectTo: 'stoppuhr'},
  {path: 'stoppuhr', component: StoppuhrComponent},
  {path: 'einstellungen', component: EinstellungenComponent},
  {path: 'systemstatus', component: SystemstatusComponent},
  {path: 'netzwerk', component: NetzwerkComponent},
  {path: '**', redirectTo: 'stoppuhr'},
];
