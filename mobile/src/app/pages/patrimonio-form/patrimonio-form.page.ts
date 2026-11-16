import { Component, OnInit } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { IpeApiService, InventoryCategory, InventoryRoom } from '../../services/ipe-api.service';

@Component({
  selector: 'app-patrimonio-form',
  templateUrl: './patrimonio-form.page.html',
  styleUrls: ['./patrimonio-form.page.scss'],
  standalone: false
})
export class PatrimonioFormPage implements OnInit {
  categorias: InventoryCategory[] = [];
  salas: InventoryRoom[] = [];
  carregandoFiltros = true;
  salvando = false;
  erro = '';
  sucesso = '';

  form = {
    nome: '',
    numero_patrimonio: '',
    valor_compra: '',
    data_aquisicao: '',
    taxa_depreciacao: '10',
    id_sala: '',
    id_categoria: ''
  };

  constructor(private api: IpeApiService, private router: Router) {}

  ngOnInit(): void {
    this.api.getInventoryFilters().subscribe({
      next: (filtros) => {
        this.categorias = filtros.categorias || [];
        this.salas = filtros.salas || [];
        this.carregandoFiltros = false;
      },
      error: () => {
        this.erro = 'Não foi possível carregar categorias e salas. Tente novamente.';
        this.carregandoFiltros = false;
      }
    });
  }

  salvar(): void {
    this.erro = '';
    this.sucesso = '';

    const nome = this.form.nome.trim();
    const numero = this.form.numero_patrimonio.trim();
    const valor = Number(this.form.valor_compra);
    const taxa = Number(this.form.taxa_depreciacao);

    if (!nome || !numero || !this.form.valor_compra.trim() || !this.form.data_aquisicao || !this.form.taxa_depreciacao.trim() || !this.form.id_categoria) {
      this.erro = 'Preencha nome, número patrimonial, data de aquisição e categoria.';
      return;
    }

    if (!Number.isFinite(valor) || valor < 0) {
      this.erro = 'Informe um valor de compra válido.';
      return;
    }

    if (!Number.isFinite(taxa) || taxa < 0 || taxa > 100) {
      this.erro = 'A taxa de depreciação deve estar entre 0 e 100%.';
      return;
    }

    const dados = new FormData();
    dados.append('nome', nome);
    dados.append('numero_patrimonio', numero);
    dados.append('valor_compra', String(valor));
    dados.append('data_aquisicao', this.form.data_aquisicao);
    dados.append('taxa_depreciacao', String(taxa));
    dados.append('id_sala', this.form.id_sala);
    dados.append('id_categoria', String(this.form.id_categoria));

    this.salvando = true;
    this.api.createInventory(dados).subscribe({
      next: (resposta) => {
        this.sucesso = resposta.mensagem || 'Patrimônio cadastrado com sucesso.';
        this.form = {
          nome: '',
          numero_patrimonio: '',
          valor_compra: '',
          data_aquisicao: '',
          taxa_depreciacao: '10',
          id_sala: '',
          id_categoria: ''
        };
        this.salvando = false;
      },
      error: (resposta: HttpErrorResponse) => {
        this.erro = resposta.error?.erro || 'Não foi possível cadastrar o patrimônio. Verifique sua permissão e os dados.';
        this.salvando = false;
      }
    });
  }

  voltarAoInventario(): void {
    this.router.navigateByUrl('/inventario');
  }
}
