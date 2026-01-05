import {Component, effect, inject} from '@angular/core';
import {MatInputModule} from '@angular/material/input';
import {MatCardModule} from '@angular/material/card';
import {FormsModule} from '@angular/forms';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatButtonModule} from '@angular/material/button';
import {StatusService} from '../../services/status.service';

@Component({
  selector: 'app-einstellungen',
  standalone: true,
  imports: [MatInputModule, MatCardModule, FormsModule, MatFormFieldModule, MatButtonModule],
  templateUrl: './einstellungen.component.html',
  styleUrl: './einstellungen.component.scss'
})
export class EinstellungenComponent {
  private statusService = inject(StatusService);

  settings = {
    startcards_base_url: '',
    startcards_suffix: ''
  };

  constructor() {
    effect(() => {
      const remoteSettings = this.statusService.settingsResource.value();
      if (remoteSettings) {
        this.settings = {...remoteSettings};
      }
    });
  }

  save() {
    this.statusService.updateSettings(this.settings).subscribe(() => {
      this.statusService.settingsResource.reload();
    });
  }

}
