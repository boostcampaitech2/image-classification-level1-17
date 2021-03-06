import argparse
import glob
import json
import multiprocessing
import os
import random
import re
import optuna

from importlib import import_module
from pathlib import Path
from tqdm import tqdm, tqdm_notebook
from sklearn.metrics import f1_score

import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import optim
from torch.optim.lr_scheduler import StepLR
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

from dataset import MaskBaseDataset
from loss import create_criterion


def seed_everything(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)  # if use multi-GPU
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)
    random.seed(seed)


def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']


def grid_image(np_images, gts, preds, n=16, shuffle=False):
    batch_size = np_images.shape[0]
    assert n <= batch_size

    choices = random.choices(range(batch_size), k=n) if shuffle else list(range(n))
    figure = plt.figure(figsize=(12, 18 + 2))  # cautions: hardcoded, 이미지 크기에 따라 figsize 를 조정해야 할 수 있습니다. T.T
    plt.subplots_adjust(top=0.8)               # cautions: hardcoded, 이미지 크기에 따라 top 를 조정해야 할 수 있습니다. T.T
    n_grid = np.ceil(n ** 0.5)
    tasks = ["mask", "gender", "age"]
    for idx, choice in enumerate(choices):
        gt = gts[choice].item()
        pred = preds[choice].item()
        image = np_images[choice]
        # title = f"gt: {gt}, pred: {pred}"
        gt_decoded_labels = MaskBaseDataset.decode_multi_class(gt)
        pred_decoded_labels = MaskBaseDataset.decode_multi_class(pred)
        title = "\n".join([
            f"{task} - gt: {gt_label}, pred: {pred_label}"
            for gt_label, pred_label, task
            in zip(gt_decoded_labels, pred_decoded_labels, tasks)
        ])

        plt.subplot(n_grid, n_grid, idx + 1, title=title)
        plt.xticks([])
        plt.yticks([])
        plt.grid(False)
        plt.imshow(image, cmap=plt.cm.binary)

    return figure


def increment_path(path, exist_ok=False):
    """ Automatically increment path, i.e. runs/exp --> runs/exp0, runs/exp1 etc.

    Args:
        path (str or pathlib.Path): f"{model_dir}/{args.name}".
        exist_ok (bool): whether increment path (increment if False).
    """
    path = Path(path)
    if (path.exists() and exist_ok) or (not path.exists()):
        return str(path)
    else:
        dirs = glob.glob(f"{path}*")
        matches = [re.search(rf"%s(\d+)" % path.stem, d) for d in dirs]
        i = [int(m.groups()[0]) for m in matches if m]
        n = max(i) + 1 if i else 2
        return f"{path}{n}"

def rand_bbox(size, lam): # size : [Batch_size, Channel, Width, Height]
    W = size[2] 
    H = size[3] 
    cut_rat = np.sqrt(1. - lam)  # 패치 크기 비율
    cut_w = np.int(W * cut_rat)
    cut_h = np.int(H * cut_rat)  

   	# 패치의 중앙 좌표 값 cx, cy
    cx = np.random.randint(W)
    cy = np.random.randint(H)
		
    # 패치 모서리 좌표 값 
    bbx1 = 0
    bby1 = np.clip(cy - cut_h // 2, 0, H)
    bbx2 = W
    bby2 = np.clip(cy + cut_h // 2, 0, H)
   
    return bbx1, bby1, bbx2, bby2

def train(data_dir, model_dir, args):
    seed_everything(args.seed)

    save_dir = increment_path(os.path.join(model_dir, args.name))

    # -- settings
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")

    # -- dataset
    dataset_module = getattr(import_module("dataset"), args.dataset)  # default: BaseAugmentation
    dataset = dataset_module(
        data_dir=data_dir,
        label=args.label
    )
    num_classes = dataset.num_classes  # 18

    # -- augmentation
    transform_module = getattr(import_module("dataset"), args.augmentation)  # default: BaseAugmentation
    transform = transform_module(
        resize=args.resize,
        mean=dataset.mean,
        std=dataset.std,
    )

    # -- data_loader
    train_set, val_set = dataset.split_dataset()
    train_set.dataset.set_transform(transform['train'])
    val_set.dataset.set_transform(transform['val'])

    train_loader = DataLoader(
        train_set,
        batch_size=args.batch_size,
        num_workers=multiprocessing.cpu_count()//2,
        shuffle=True,
        pin_memory=use_cuda,
        drop_last=True,
    )

    val_loader = DataLoader(
        val_set,
        batch_size=args.valid_batch_size,
        num_workers=multiprocessing.cpu_count()//2,
        shuffle=False,
        pin_memory=use_cuda,
        drop_last=True,
    )

    # -- model
    model_module = getattr(import_module("model"), args.model)  # default: BaseModel

    if args.model in ['EfficientNet', 'ViT', 'EfficientNet_v2']:
        model = model_module(
            num_classes=num_classes,
            version=args.model_version,
        ).to(device)
    else:
        model = model_module(
            num_classes=num_classes
        ).to(device)
    model = torch.nn.DataParallel(model)

    # -- loss & metric
    criterion = create_criterion(args.criterion)  # default: cross_entropy
    opt_module = getattr(import_module("torch.optim"), args.optimizer)  # default: SGD
    optimizer = opt_module(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=args.lr,
        weight_decay=5e-4
    )
    if not args.optuna:
        scheduler = StepLR(optimizer, args.lr_decay_step, gamma=args.lr_gamma)

    # -- logging
    logger = SummaryWriter(log_dir=save_dir)
    with open(os.path.join(save_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(vars(args), f, ensure_ascii=False, indent=4)

    best_val_f1 = 0
    best_val_loss = np.inf
    for epoch in range(args.epochs):
        # train loop
        model.train()
        loss_value = 0
        matches = 0
        f1_value = 0
        for idx, train_batch in enumerate(tqdm(train_loader,leave=True)):
            inputs, labels = train_batch
            inputs = inputs['image'].to(device)
            labels = labels.to(device)

            optimizer.zero_grad()

            if args.beta > 0 and np.random.random()>0.5: # cutmix가 실행될 경우     
                lam = np.random.beta(args.beta, args.beta)
                rand_index = torch.randperm(inputs.size()[0]).to(device)
                target_a = labels # 원본 이미지 label
                target_b = labels[rand_index] # 패치 이미지 label       
                bbx1, bby1, bbx2, bby2 = rand_bbox(inputs.size(), lam)
                inputs[:, :, bbx1:bbx2, bby1:bby2] = inputs[rand_index, :, bbx1:bbx2, bby1:bby2]
                lam = 1 - ((bbx2 - bbx1) * (bby2 - bby1) / (inputs.size()[-1] * inputs.size()[-2]))
                outs = model(inputs)
                loss = criterion(outs, target_a) * lam + criterion(outs, target_b) * (1. - lam) # 패치 이미지와 원본 이미지의 비율에 맞게 loss를 계산을 해주는 부분
                _, preds= torch.max(outs, 1) 
            
            else: # cutmix가 실행되지 않았을 경우
                outs= model(inputs) 
                loss= criterion(outs, labels)
                
            if args.beta > 0: # cutmix가 실행 되었을 때 preds 설정
                _, preds= torch.max(outs, 1) 

            else:
                preds = torch.argmax(outs, dim=-1)

            loss.backward()
            optimizer.step()

            loss_value += loss.item()
            matches += (preds == labels).sum().item()
            f1_value += f1_score(outs.argmax(dim=1).cpu(), labels.cpu(), average='macro')

            acc = (outs.argmax(dim=1) == labels).float().mean()

            if (idx + 1) % args.log_interval == 0:
                train_loss = loss_value / args.log_interval
                train_acc = matches / args.batch_size / args.log_interval
                train_f1 = f1_value / args.log_interval

                current_lr = get_lr(optimizer)
                print(
                    f"Epoch[{epoch}/{args.epochs}]({idx + 1}/{len(train_loader)}) || "
                    f"training loss {train_loss:4.4} || training accuracy {train_acc:4.2%} || training f1 {train_f1:4.2%} || lr {current_lr}"
                )
                logger.add_scalar("Train/loss", train_loss, epoch * len(train_loader) + idx)
                logger.add_scalar("Train/accuracy", train_acc, epoch * len(train_loader) + idx)
                logger.add_scalar("Train/f1", train_f1, epoch * len(train_loader) + idx)

                loss_value = 0
                matches = 0
                f1_value = 0
        if not args.optuna:
            scheduler.step()

        # val loop
        with torch.no_grad():
            print("Calculating validation results...")
            model.eval()
            val_loss_items = 0
            val_acc_items = 0
            val_f1_items = 0
            figure = None
            for val_batch in val_loader:
                inputs, labels = val_batch
                inputs = inputs['image'].to(device)
                labels = labels.to(device)

                outs = model(inputs)
                preds = torch.argmax(outs, dim=-1)

                val_loss_items += criterion(outs, labels).item()
                val_acc_items += (labels == preds).sum().item()
                val_f1_items += f1_score(outs.argmax(dim=1).cpu(), labels.cpu(), average='macro')


                if figure is None:
                    inputs_np = torch.clone(inputs).detach().cpu().permute(0, 2, 3, 1).numpy()
                    inputs_np = dataset_module.denormalize_image(inputs_np, dataset.mean, dataset.std)
                    figure = grid_image(
                        inputs_np, labels, preds, n=16, shuffle=args.dataset != "MaskSplitByProfileDataset"
                    )

            val_loss = val_loss_items / len(val_loader)
            val_acc = val_acc_items / len(val_set)
            val_f1 = val_f1_items / len(val_loader)

            best_val_loss = min(best_val_loss, val_loss)
            if val_f1 > best_val_f1:
                print(f"New best model for val f1 : {val_f1:4.2%}! saving the best model..")
                torch.save(model.module.state_dict(), f"{save_dir}/best.pth")
                best_val_f1 = val_f1
            torch.save(model.module.state_dict(), f"{save_dir}/last.pth")
            print(
                f"[Val] f1 : {val_f1:4.2%}, loss: {val_loss:4.2} || "
                f"best f1 : {best_val_f1:4.2%}, best loss: {best_val_loss:4.2}"
            )

            logger.add_scalar("Val/loss", val_loss, epoch)
            logger.add_scalar("Val/accuracy", val_acc, epoch)
            logger.add_scalar("Val/f1", val_f1, epoch)
            logger.add_figure("results", figure, epoch)
            print()
    return best_val_f1

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    from dotenv import load_dotenv
    import os
    load_dotenv(verbose=True)

    # Data and model checkpoints directories
    parser.add_argument('--seed', type=int, default=42, help='random seed (default: 42)')
    parser.add_argument('--epochs', type=int, default=1, help='number of epochs to train (default: 1)')
    parser.add_argument('--dataset', type=str, default='MaskSplitByProfileDataset', help='dataset augmentation type (default: MaskBaseDataset)')
    parser.add_argument('--label', type=str, default='total', help='dataset label: (total, mask, age, gender) (default: total)')
    parser.add_argument('--augmentation', type=str, default='get_transforms', help='data augmentation type (default: BaseAugmentation)')
    parser.add_argument("--resize", nargs="+", type=int, default=[512, 384], help='resize size for image when training')
    parser.add_argument('--batch_size', type=int, default=64, help='input batch size for training (default: 64)')
    parser.add_argument('--valid_batch_size', type=int, default=64, help='input batch size for validing (default: 64)')
    parser.add_argument('--model', type=str, default='BaseModel', help='model type (default: BaseModel)')
    parser.add_argument('--optimizer', type=str, default='SGD', help='optimizer type (default: SGD)')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate (default: 1e-3)')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='ratio for validaton (default: 0.2)')
    parser.add_argument('--criterion', type=str, default='cross_entropy', help='criterion type (default: cross_entropy)')
    parser.add_argument('--lr_decay_step', type=int, default=20, help='learning rate scheduler deacy step (default: 20)')
    parser.add_argument('--lr_gamma', type=float, default=0.5, help='learning rate scheduler gamma (default: 0.5)')
    parser.add_argument('--log_interval', type=int, default=20, help='how many batches to wait before logging training status')
    parser.add_argument('--name', default='exp', help='model save at {SM_MODEL_DIR}/{name}')

    parser.add_argument('--model_version', type=str, default='b0', help='model version (default: b0)')
    parser.add_argument('--cpu', type=bool, default=False, help='if you want to use cpu')
    parser.add_argument('--tb', type=bool, default=True, help='use tensorboard')
    parser.add_argument('--beta', type=float, default=-1.0, help='beta (default: -1)')

    # Optuna Setting
    parser.add_argument('--optuna', type=bool, default=False, help='use optuna')
    parser.add_argument('--optuna_ntrials', type=int, default=10, help='if you use optuna, set optuna epoch')
    parser.add_argument('--optuna_epoch_min', type=int, default=3, help='optuna epoch min')
    parser.add_argument('--optuna_epoch_max', type=int, default=5, help='optuna epoch max')
    parser.add_argument('--optuna_lr_min', type=float, default=1e-5, help='optuna lr min')
    parser.add_argument('--optuna_lr_max', type=float, default=1e-2, help='optuna lr max')
    parser.add_argument('--optuna_optimizer', nargs="+", type=float, default=['Adadelta', 'AdamW', 'SGD', 'RMSprop', 'Adam', 'Adagrad'], help='optuna optimizer list')

    # Container environment
    parser.add_argument('--data_dir', type=str, default=os.environ.get('SM_CHANNEL_TRAIN', '/opt/ml/input/data/train/images'))
    parser.add_argument('--model_dir', type=str, default=os.environ.get('SM_MODEL_DIR', './model'))

    args = parser.parse_args()

    data_dir = args.data_dir
    model_dir = args.model_dir
    if args.optuna:
        def train_optuna(trial):
            # optuna Setting
            args.epochs = trial.suggest_int('n_epochs', args.optuna_epoch_min, args.optuna_epoch_max)
            args.lr = trial.suggest_loguniform('lr', args.optuna_lr_min, args.optuna_lr_max)
            args.optimizer = trial.suggest_categorical('optimizer', args.optuna_optimizer)
            print(args)
            return train(data_dir, model_dir, args)
        study = optuna.create_study(direction='maximize') 
        study.optimize(train_optuna, n_trials=args.optuna_ntrials)
        print(f"Best F1 Val: {study.best_trial.value}\n Params\n {study.best_trial.params}\n Save at {model_dir}/optuna.json")
        with open(os.path.join(model_dir, f'optuna_{args.name}_{study.best_trial.value}.json'), 'w', encoding='utf-8') as f:\
            json.dump(study.best_trial.params, f, ensure_ascii=False, indent=4)
    else:
        print(args)
        train(data_dir, model_dir, args)