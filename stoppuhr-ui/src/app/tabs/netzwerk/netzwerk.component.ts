import {Component} from '@angular/core';
import {CommonModule} from '@angular/common';
import {MatCardModule} from '@angular/material/card';
import {MatFormField, MatInput, MatLabel} from '@angular/material/input';
import {FormsModule} from '@angular/forms';
import {MatButton} from '@angular/material/button';

@Component({
  selector: 'app-netzwerk',
  templateUrl: './netzwerk.component.html',
  styleUrls: ['./netzwerk.component.scss'],
  standalone: true,
  imports: [CommonModule, MatCardModule, MatFormField, MatLabel, FormsModule, MatButton, MatInput],
})
export class NetzwerkComponent {
  // stub
  host = '192.168.178.33';
  port = 8082;
}
