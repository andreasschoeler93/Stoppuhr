import {Component} from '@angular/core';
import {MatCardModule} from '@angular/material/card';
import {MatFormField, MatInput, MatLabel} from '@angular/material/input';
import {FormsModule} from '@angular/forms';
import {MatButton} from '@angular/material/button';

@Component({
  selector: 'app-einstellungen',
  standalone: true,
  imports: [MatCardModule, MatFormField, MatLabel, FormsModule, MatButton, MatInput],
  templateUrl: './einstellungen.component.html',
  styleUrl: './einstellungen.component.scss'
})
export class EinstellungenComponent {
  startkartenPfad = '/api/startkarten';
}
