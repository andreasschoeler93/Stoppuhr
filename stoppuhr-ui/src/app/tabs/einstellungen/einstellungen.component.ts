import {Component} from '@angular/core';
import {MatInputModule} from '@angular/material/input';
import {MatCardModule} from '@angular/material/card';
import {FormsModule} from '@angular/forms';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatButtonModule} from '@angular/material/button';

@Component({
  selector: 'app-einstellungen',
  standalone: true,
  imports: [MatInputModule, MatCardModule, FormsModule, MatFormFieldModule, MatButtonModule],
  templateUrl: './einstellungen.component.html',
  styleUrl: './einstellungen.component.scss'
})
export class EinstellungenComponent {
  startkartenPfad = '/api/startkarten';
}
