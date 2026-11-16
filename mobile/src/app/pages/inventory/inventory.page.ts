import { Component, OnInit } from '@angular/core';
import { IpeApiService, InventoryItem } from '../../services/ipe-api.service';

@Component({
  selector: 'app-inventory',
  templateUrl: './inventory.page.html',
  styleUrls: ['./inventory.page.scss'],
  standalone: false
})
export class InventoryPage implements OnInit {
  itens: InventoryItem[] = [];
  busca = '';
  carregando = true;
  erro = '';
  podeCadastrar = false;

  constructor(private api: IpeApiService) {}

  ngOnInit(): void {
    this.carregar();
    this.api.currentUser().subscribe({
      next: (usuario) => this.podeCadastrar = usuario.id_perfil === 1,
      error: () => this.podeCadastrar = false
    });
  }

  carregar(): void {
    this.api.getInventory().subscribe({
      next: (dados) => {
        this.itens = dados;
        this.carregando = false;
      },
      error: () => {
        this.erro = 'Não foi possível carregar o inventário.';
        this.carregando = false;
      }
    });
  }

  get filtrados(): InventoryItem[] {
    const termo = this.busca.toLocaleLowerCase('pt-BR').trim();
    return this.itens.filter((item) =>
      !termo || [item.nome, item.numero_patrimonio, item.nome_sala]
        .some((valor) => (valor || '').toLocaleLowerCase('pt-BR').includes(termo))
    );
  }
}
